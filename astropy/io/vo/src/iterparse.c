/*
Copyright (C) 2008-2010 Association of Universities for Research in Astronomy (AURA)

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

    1. Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.

    2. Redistributions in binary form must reproduce the above
      copyright notice, this list of conditions and the following
      disclaimer in the documentation and/or other materials provided
      with the distribution.

    3. The name of AURA and its representatives may not be used to
      endorse or promote products derived from this software without
      specific prior written permission.

THIS SOFTWARE IS PROVIDED BY AURA ``AS IS'' AND ANY EXPRESS OR IMPLIED
WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL AURA BE LIABLE FOR ANY DIRECT, INDIRECT,
INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS
OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR
TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE
USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH
DAMAGE.
*/

/******************************************************************************
 * C extension code for vo.table.
 *
 * Everything in this file has an alternate Python implementation and
 * is included for performance reasons only.
 *
 * It has three main parts:
 *
 *   - An IterParser object which parses an XML file using the expat
 *     library, feeding expat events through a Python iterator.  It is
 *     faster and more memory efficient than the alternatives in the
 *     Python standard library because it does not build a tree of
 *     objects, and also throws away most text nodes, since for VO we
 *     only care about simple text nodes contained between a single
 *     pair of open/close element nodes.  It also has an optimization
 *     for recognizing the most commonly occuring element in a VO
 *     file, "TD".
 *
 *   - An write_tabledata function to quickly write out a Numpy array
 *     in TABLEDATA format.
 *
 *   - Two functions, escape_xml() and escape_xml_cdata() that escape
 *     XML much faster than the alternatives in the Python standard
 *     library.
 ******************************************************************************/

#include <Python.h>
#include "structmember.h"

#include "expat.h"

/******************************************************************************
 * Convenience macros and functions
 ******************************************************************************/
#undef  CLAMP
#define CLAMP(x, low, high)  (((x) > (high)) ? (high) : (((x) < (low)) ? (low) : (x)))

static Py_ssize_t
next_power_of_2(Py_ssize_t n)
{
    /* Calculate the next-highest power of two */
    n--;
    n |= n >> 1;
    n |= n >> 2;
    n |= n >> 4;
    n |= n >> 8;
    n |= n >> 16;
    n++;

    return n;
}

/******************************************************************************
 * Python version compatibility macros
 ******************************************************************************/
#if PY_VERSION_HEX < 0x02050000 && !defined(PY_SSIZE_T_MIN)
typedef int Py_ssize_t;
#  define PY_SSIZE_T_MAX INT_MAX
#  define PY_SSIZE_T_MIN INT_MIN
#endif

#if PY_MAJOR_VERSION >= 3
#  define IS_PY3K
#endif

#ifdef IS_PY3K
#  define PyString_InternFromString  PyUnicode_InternFromString
#  define PyString_FromString        PyUnicode_FromString
#  define PyString_FromStringAndSize PyUnicode_FromStringAndSize
#  define PyInt_FromSsize_t          PyLong_FromSsize_t
#  define PyString_AsStringAndSize   PyBytes_AsStringAndSize
#  define PyInt_FromSize_t           PyLong_FromSize_t
#else
#  ifndef Py_TYPE
#    define Py_TYPE(o) ((o)->ob_type)
#  endif
#endif

#if BYTEORDER == 1234
# define TD_AS_INT      0x00004454
# define TD_AS_INT_MASK 0x00ffffff
#else
# define TD_AS_INT      0x54440000
# define TD_AS_INT_MASK 0xffffff00
#endif

/******************************************************************************
 * IterParser type
 ******************************************************************************/
typedef struct {
    PyObject_HEAD
    XML_Parser parser;          /* The expat parser */
    int        done;            /* True when expat parser has read to EOF */

    /* File-like object reading */
    PyObject*  fd;              /* Python file object */
#ifdef IS_PY3K
    int        file;            /* C file descriptor */
#else
    FILE*      file;            /* C FILE pointer */
#endif
    PyObject*  read;            /* The read method on the file object */
    ssize_t    buffersize;      /* The size of the read buffer */
    XML_Char*  buffer;          /* The read buffer */

    /* Text nodes */
    Py_ssize_t text_alloc;      /* The allocated size of the text buffer */
    Py_ssize_t text_size;       /* The size of the content in the text buffer */
    XML_Char*  text;            /* Text buffer (for returning text nodes) */
    int        keep_text;       /* Flag: keep appending text chunks to the current text node */

    /* XML event queue */
    PyObject** queue;
    Py_ssize_t queue_size;
    Py_ssize_t queue_read_idx;
    Py_ssize_t queue_write_idx;

    /* Store the last Python exception so it can be returned when
       dequeing events */
    PyObject*  error_type;
    PyObject*  error_value;
    PyObject*  error_traceback;

    /* "Constants" for efficiency */
    PyObject*  dict_singleton;  /* Empty dict */
    PyObject*  td_singleton;    /* String "TD" */
    PyObject*  read_args;       /* (buffersize) */
} IterParser;

/******************************************************************************
 * Text buffer
 ******************************************************************************/

/**
 * Reallocate text buffer to the next highest power of two that fits the
 * requested size.
 */
static int
text_realloc(IterParser *self, Py_ssize_t req_size)
{
    Py_ssize_t  n       = req_size;
    char       *new_mem = NULL;

    if (req_size < self->text_alloc) {
        return 0;
    }

    /* Calculate the next-highest power of two */
    n = next_power_of_2(n);

    if (n < req_size) {
        PyErr_SetString(PyExc_MemoryError, "Out of memory for XML text.");
        return -1;
    }

    new_mem = malloc(n * sizeof(XML_Char));
    if (new_mem == NULL) {
        PyErr_SetString(PyExc_MemoryError, "Out of memory for XML text.");
        return -1;
    }

    memcpy(new_mem, self->text, (size_t)(self->text_size + 1) * sizeof(XML_Char));

    free(self->text);
    self->text = new_mem;
    self->text_alloc = n;

    return 0;
}

#define IS_WHITESPACE(c) ((c) == (XML_Char)0x20 || \
                          (c) == (XML_Char)0x0d || \
                          (c) == (XML_Char)0x0a || \
                          (c) == (XML_Char)0x09)

/*
 * Append text to the text buffer.
 *
 * For the first chunk of text, all whitespace characters before the
 * first non-whitespace character are stripped.  This saves time
 * stripping on the Python side later.
 */
static int
text_append(IterParser *self, const XML_Char *data, Py_ssize_t len)
{
    Py_ssize_t new_size;

    if (len == 0) {
        return 0;
    }

    /* If this is the first chunk, handle whitespace */
    if (self->text_size == 0) {
        while (len && IS_WHITESPACE(*data)) {
            ++data;
            --len;
        }
    }

    /* Grow text buffer if necessary */
    new_size = self->text_size + len;
    if (text_realloc(self, new_size + 1)) {
        return -1;
    }

    memcpy(self->text + self->text_size,
           data,
           (size_t)len * sizeof(XML_Char));

    self->text_size = new_size;
    self->text[self->text_size] = (XML_Char)0x0;

    return 0;
}

/*
 * Erase all content from the text buffer.
 */
static void
text_clear(IterParser *self)
{
    self->text[0] = (XML_Char)0;
    self->text_size = 0;
}

/******************************************************************************
 * XML event handling
 ******************************************************************************/

/*
 * Make a "position tuple" from the current expat parser state.  This
 * is used to communicate the position of the parser within the file
 * to the Python side for generation of meaningful error messages.
 *
 * It is of the form (line, col), where line and col are both PyInts.
 */
static inline PyObject*
make_pos(const IterParser *self)
{
    unsigned long line;
    unsigned long col;
    PyObject* tuple;
    PyObject* line_obj;
    PyObject* col_obj;
    
    line = (unsigned long)XML_GetCurrentLineNumber(self->parser);
    col = (unsigned long)XML_GetCurrentColumnNumber(self->parser);

    tuple = PyTuple_New(2);

    line_obj = PyInt_FromSize_t((size_t)line);
    col_obj = PyInt_FromSize_t((size_t)col);

    PyTuple_SetItem(tuple, 0, line_obj);
    PyTuple_SetItem(tuple, 1, col_obj);

    return tuple;
}

/*
 * Removes the namespace from an element or attribute name, that is,
 * remove everything before the first colon.  The namespace is not
 * needed to parse standards-compliant VOTable files.
 *
 * The returned pointer is an internal pointer to the buffer passed
 * in.
 */
static const XML_Char *
remove_namespace(const XML_Char *name)
{
    const XML_Char*  name_start = NULL;

    /* If there is a namespace specifier, just chop it off */
    name_start = name;
    for (name_start = name; *name_start != '\0'; ++name_start) {
        if (*name_start == ':') {
            break;
        }
    }

    if (*name_start == ':') {
        ++name_start;
    } else {
        name_start = name;
    }

    return name_start;
}

/*
 * Handle the expat startElement event.
 */
static void
startElement(IterParser *self, const XML_Char *name, const XML_Char **atts)
{
    PyObject*        pyname = NULL;
    PyObject*        pyatts = NULL;
    const XML_Char** att_ptr = atts;
    const XML_Char*  name_start = NULL;
    PyObject*        tuple = NULL;
    PyObject*        key = NULL;
    PyObject*        val = NULL;

    /* If we've already had an error in a previous call, don't make
       things worse. */
    if (PyErr_Occurred() != NULL) {
        XML_StopParser(self->parser, 0);
        return;
    }

    /* Don't overflow the queue -- in practice this should *never* happen */
    if (self->queue_write_idx < self->queue_size) {
        tuple = PyTuple_New(4);
        if (tuple == NULL) {
            XML_StopParser(self->parser, 0);
            return;
        }

        Py_INCREF(Py_True);
        PyTuple_SET_ITEM(tuple, 0, Py_True);

        /* This is an egregious but effective optimization.  Since by
           far the most frequently occurring element name in a large
           VOTABLE file is TD, we explicitly check for it here with
           integer comparison to avoid the lookup in the interned
           string table in PyString_InternFromString, and return a
           singleton string for "TD" */
        if ((*(int*)name & TD_AS_INT_MASK) == TD_AS_INT) {
            Py_INCREF(self->td_singleton);
            PyTuple_SetItem(tuple, 1, self->td_singleton);
        } else {
            name_start = remove_namespace(name);

            pyname = PyString_FromString(name_start);
            if (pyname == NULL) {
                Py_DECREF(tuple);
                XML_StopParser(self->parser, 0);
                return;
            }
            PyTuple_SetItem(tuple, 1, pyname);
        }

        if (*att_ptr) {
            pyatts = PyDict_New();
            if (pyatts == NULL) {
                Py_DECREF(tuple);
                XML_StopParser(self->parser, 0);
                return;
            }
            do {
                if (*(*(att_ptr + 1)) != 0) {
                    key = PyString_FromString(*att_ptr);
                    if (key == NULL) {
                        Py_DECREF(tuple);
                        XML_StopParser(self->parser, 0);
                        return;
                    }
                    val = PyString_FromString(*(att_ptr + 1));
                    if (val == NULL) {
                        Py_DECREF(key);
                        Py_DECREF(tuple);
                        XML_StopParser(self->parser, 0);
                        return;
                    }
                    if (PyDict_SetItem(pyatts, key, val)) {
                        Py_DECREF(pyatts);
                        Py_DECREF(tuple);
                        Py_DECREF(key);
                        Py_DECREF(val);
                        XML_StopParser(self->parser, 0);
                        return;
                    }
                    Py_DECREF(key);
                    Py_DECREF(val);
                }
                att_ptr += 2;
            } while (*att_ptr);
        } else {
            Py_INCREF(self->dict_singleton);
            pyatts = self->dict_singleton;
        }

        PyTuple_SetItem(tuple, 2, pyatts);

        PyTuple_SetItem(tuple, 3, make_pos(self));

        text_clear(self);

        self->keep_text = 1;

        self->queue[self->queue_write_idx++] = tuple;
    } else {
        PyErr_SetString(
            PyExc_RuntimeError,
            "XML queue overflow in startElement.  This most likely indicates an internal bug.");
    }
}

/*
 * Handle the expat endElement event.
 */
static void
endElement(IterParser *self, const XML_Char *name)
{
    PyObject*       pyname     = NULL;
    PyObject*       tuple      = NULL;
    PyObject*       pytext     = NULL;
    const XML_Char* name_start = NULL;
    XML_Char*       end;

    /* If we've already had an error in a previous call, don't make
       things worse. */
    if (PyErr_Occurred() != NULL) {
        XML_StopParser(self->parser, 0);
        return;
    }

    /* Don't overflow the queue -- in practice this should *never* happen */
    if (self->queue_write_idx < self->queue_size) {
        tuple = PyTuple_New(4);
        if (tuple == NULL) {
            XML_StopParser(self->parser, 0);
            return;
        }

        Py_INCREF(Py_False);
        PyTuple_SET_ITEM(tuple, 0, Py_False);

        /* This is an egregious but effective optimization.  Since by
           far the most frequently occurring element name in a large
           VOTABLE file is TD, we explicitly check for it here with
           integer comparison to avoid the lookup in the interned
           string table in PyString_InternFromString, and return a
           singleton string for "TD" */
        if ((*(int*)name & TD_AS_INT_MASK) == TD_AS_INT) {
            Py_INCREF(self->td_singleton);
            PyTuple_SetItem(tuple, 1, self->td_singleton);
        } else {
            name_start = remove_namespace(name);

            pyname = PyString_FromString(name_start);
            if (pyname == NULL) {
                Py_DECREF(tuple);
                XML_StopParser(self->parser, 0);
                return;
            }
            PyTuple_SetItem(tuple, 1, pyname);
        }

        /* Cut whitespace off the end of the string */
        end = self->text + self->text_size - 1;
        while (end >= self->text && IS_WHITESPACE(*end)) {
            --end;
            --self->text_size;
        }
        pytext = PyString_FromStringAndSize(self->text, self->text_size);
        if (pytext == NULL) {
            Py_DECREF(tuple);
            XML_StopParser(self->parser, 0);
            return;
        }
        PyTuple_SetItem(tuple, 2, pytext);

        PyTuple_SetItem(tuple, 3, make_pos(self));

        self->keep_text = 0;

        self->queue[self->queue_write_idx++] = tuple;
    } else {
        PyErr_SetString(
            PyExc_RuntimeError,
            "XML queue overflow in endElement.  This most likely indicates an internal bug.");
    }
}

/*
 * Handle the expat characterData event.
 */
static void
characterData(IterParser *self, const XML_Char *text, int len)
{
    /* If we've already had an error in a previous call, don't make
       things worse. */
    if (PyErr_Occurred() != NULL) {
        XML_StopParser(self->parser, 0);
        return;
    }

    if (self->keep_text) {
        (void)text_append(self, text, (Py_ssize_t)len);
    }
}

/*
 * The object itself is an iterator, just return self for "iter(self)"
 * on the Python side.
 */
static PyObject *
IterParser_iter(IterParser* self)
{
    Py_INCREF(self);
    return (PyObject*) self;
}

/*
 * Get the next element from the iterator.
 *
 * The expat event handlers above (startElement, endElement, characterData) add
 * elements to the queue, which are then dequeued by this method.
 *
 * Care must be taken to store and later raise exceptions.  Any
 * exceptions raised in the expat callbacks must be stored and then
 * later thrown once the queue is emptied, otherwise the exception is
 * raised "too early" in queue order.
 */
static PyObject *
IterParser_next(IterParser* self)
{
    PyObject*  data = NULL;
    XML_Char*  buf;
    Py_ssize_t buflen;

    /* Is there anything in the queue to return? */
    if (self->queue_read_idx < self->queue_write_idx) {
        return self->queue[self->queue_read_idx++];
    }

    /* Now that the queue is empty, is there an error we need to raise? */
    if (self->error_type) {
        PyErr_Restore(self->error_type, self->error_value, self->error_traceback);
        self->error_type = NULL;
        self->error_value = NULL;
        self->error_traceback = NULL;
        return NULL;
    }

    /* The queue is empty -- have we already fed the entire file to
       expat?  If so, we are done and indicate the end of the iterator
       by simply returning NULL. */
    if (self->done) {
        return NULL;
    }

    self->queue_read_idx = 0;
    self->queue_write_idx = 0;

    do {
        /* Handle a generic Python read method */
        if (self->read) {
            data = PyObject_CallObject(self->read, self->read_args);
            if (data == NULL) {
                goto fail;
            }

            if (PyString_AsStringAndSize(data, &buf, &buflen) == -1) {
                Py_DECREF(data);
                goto fail;
            }

            if (buflen < self->buffersize) {
                self->done = 1;
            }
        /* Handle a real C file descriptor or handle -- this is faster
           if we've got one. */
        } else {
#ifdef IS_PY3K
            buflen = (Py_ssize_t)read(
                self->file, self->buffer, (size_t)self->buffersize);
            if (buflen < self->buffersize) {
                self->done = 1;
            } else if (buflen == -1) {
                PyErr_SetFromErrno(PyExc_IOError);
                goto fail;
            }
#else
            buflen = (Py_ssize_t)fread(
                self->buffer, 1, (size_t)self->buffersize, self->file);
            if (buflen < self->buffersize) {
                if (feof(self->file)) {
                    self->done = 1;
                } else if (ferror(self->file)) {
                    PyErr_SetFromErrno(PyExc_IOError);
                    goto fail;
                } else {
                    PyErr_SetString(PyExc_RuntimeError, "Undefined C I/O error");
                    goto fail;
                }
            }
#endif

            buf = self->buffer;
        }

        /* Feed the read buffer to expat, which will call the event handlers */
        if (XML_Parse(self->parser, buf, (int)buflen, self->done) == XML_STATUS_ERROR) {
            /* One of the event handlers raised a Python error, make
               note of it -- it won't be thrown until the queue is
               emptied. */
            if (PyErr_Occurred() != NULL) {
                goto fail;
            }

            /* expat raised an error, make note of it -- it won't be thrown
               until the queue is emptied. */
            PyErr_Format(
                PyExc_ValueError, "%lu:%lu: %s",
                XML_GetCurrentLineNumber(self->parser),
                XML_GetCurrentColumnNumber(self->parser),
                XML_ErrorString(XML_GetErrorCode(self->parser)));
            Py_XDECREF(data);
            goto fail;
        }
        Py_XDECREF(data);

        if (PyErr_Occurred() != NULL) {
            goto fail;
        }
    } while (self->queue_write_idx == 0 && self->done == 0);

    if (self->queue_write_idx == 0) {
        return NULL;
    }

    if (self->queue_write_idx >= self->queue_size) {
        PyErr_SetString(
            PyExc_RuntimeError,
            "XML queue overflow.  This most likely indicates an internal bug.");
        return NULL;
    }

    return self->queue[self->queue_read_idx++];

 fail:
    /* We got an exception somewhere along the way.  Store the exception in
       the IterParser object, but clear the exception in the Python interpreter,
       so we can empty the event queue and raise the exception later. */
    PyErr_Fetch(&self->error_type, &self->error_value, &self->error_traceback);
    PyErr_Clear();

    if (self->queue_read_idx < self->queue_write_idx) {
        return self->queue[self->queue_read_idx++];
    }

    PyErr_Restore(self->error_type, self->error_value, self->error_traceback);
    self->error_type = NULL;
    self->error_value = NULL;
    self->error_traceback = NULL;
    return NULL;
}

/******************************************************************************
 * IterParser object lifetime
 ******************************************************************************/

/* To support cyclical garbage collection, all PyObject's must be
   visited. */
static int
IterParser_traverse(IterParser *self, visitproc visit, void *arg)
{
    int vret;
    Py_ssize_t read_index;

    read_index = self->queue_read_idx;
    while (read_index < self->queue_write_idx) {
        vret = visit(self->queue[read_index++], arg);
        if (vret != 0) return vret;
    }

    if (self->fd) {
        vret = visit(self->fd, arg);
        if (vret != 0) return vret;
    }

    if (self->read) {
        vret = visit(self->read, arg);
        if (vret != 0) return vret;
    }

    if (self->read_args) {
        vret = visit(self->read_args, arg);
        if (vret != 0) return vret;
    }

    if (self->dict_singleton) {
        vret = visit(self->dict_singleton, arg);
        if (vret != 0) return vret;
    }

    if (self->td_singleton) {
        vret = visit(self->td_singleton, arg);
        if (vret != 0) return vret;
    }

    if (self->error_type) {
        vret = visit(self->error_type, arg);
        if (vret != 0) return vret;
    }

    if (self->error_value) {
        vret = visit(self->error_value, arg);
        if (vret != 0) return vret;
    }

    if (self->error_traceback) {
        vret = visit(self->error_traceback, arg);
        if (vret != 0) return vret;
    }

    return 0;
}

/* To support cyclical garbage collection */
static int
IterParser_clear(IterParser *self)
{
    PyObject *tmp;

    while (self->queue_read_idx < self->queue_write_idx) {
        tmp = self->queue[self->queue_read_idx];
        self->queue[self->queue_read_idx] = NULL;
        Py_XDECREF(tmp);
        self->queue_read_idx++;
    }

    tmp = self->fd;
    self->fd = NULL;
    Py_XDECREF(tmp);

    tmp = self->read;
    self->read = NULL;
    Py_XDECREF(tmp);

    tmp = self->read_args;
    self->read_args = NULL;
    Py_XDECREF(tmp);

    tmp = self->dict_singleton;
    self->dict_singleton = NULL;
    Py_XDECREF(tmp);

    tmp = self->td_singleton;
    self->td_singleton = NULL;
    Py_XDECREF(tmp);

    tmp = self->error_type;
    self->error_type = NULL;
    Py_XDECREF(tmp);

    tmp = self->error_value;
    self->error_value = NULL;
    Py_XDECREF(tmp);

    tmp = self->error_traceback;
    self->error_traceback = NULL;
    Py_XDECREF(tmp);

    return 0;
}

/*
 * Deallocate the IterParser object.  For the internal PyObject*, just
 * punt to IterParser_clear.
 */
static void
IterParser_dealloc(IterParser* self)
{
    IterParser_clear(self);

    free(self->buffer); self->buffer = NULL;
    free(self->queue);  self->queue = NULL;
    free(self->text);   self->text = NULL;
    if (self->parser != NULL) {
        XML_ParserFree(self->parser);
        self->parser = NULL;
    }

    Py_TYPE(self)->tp_free((PyObject*)self);
}

/*
 * Initialize the memory for an IterParser object
 */
static PyObject *
IterParser_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    IterParser *self = NULL;

    self = (IterParser *)type->tp_alloc(type, 0);
    if (self != NULL) {
        self->parser          = NULL;
        self->fd              = NULL;
#ifdef IS_PY3K
        self->file            = -1;
#else
        self->file            = NULL;
#endif
        self->read            = NULL;
        self->read_args       = NULL;
        self->dict_singleton  = NULL;
        self->td_singleton    = NULL;
        self->buffersize      = 0;
        self->buffer          = NULL;
        self->queue_read_idx  = 0;
        self->queue_write_idx = 0;
        self->text_alloc      = 0;
        self->text_size       = 0;
        self->text            = NULL;
        self->keep_text       = 0;
        self->done            = 0;
        self->queue_size      = 0;
        self->queue           = NULL;
        self->error_type      = NULL;
        self->error_value     = NULL;
        self->error_traceback = NULL;
    }

    return (PyObject *)self;
}

/*
 * Initialize an IterParser object
 *
 * The Python arguments are:
 *
 *    *fd*: A Python file object or a callable object
 *    *buffersize*: The size of the read buffer
 */
static int
IterParser_init(IterParser *self, PyObject *args, PyObject *kwds)
{
    PyObject* fd              = NULL;
    ssize_t   buffersize      = 1 << 14;

    static char *kwlist[] = {"fd", "buffersize", NULL};
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "O|n:IterParser.__init__", kwlist,
                                     &fd, &buffersize)) {
        return -1;
    }

    /* Keep the buffersize within a reasonable range */
    self->buffersize = CLAMP(buffersize, (ssize_t)(1 << 10), (ssize_t)(1 << 24));
#ifdef IS_PY3K
    self->file = PyObject_AsFileDescriptor(fd);
    if (self->file != -1) {
#else
    if (PyFile_CheckExact(fd)) {
#endif
        /* This is a real C file handle or descriptor.  We therefore
           need to allocate our own read buffer, and get the real C
           object. */
        self->buffer = malloc((size_t)self->buffersize);
        if (self->buffer == NULL) {
            PyErr_SetString(PyExc_MemoryError, "Out of memory");
            goto fail;
        }
        self->fd = fd;   Py_INCREF(self->fd);
#ifndef IS_PY3K
        self->file = PyFile_AsFile(fd);
#endif
    } else if (PyCallable_Check(fd)) {
        /* fd is a Python callable */
        self->fd = fd;   Py_INCREF(self->fd);
        self->read = fd; Py_INCREF(self->read);
    } else {
        PyErr_SetString(
            PyExc_TypeError,
            "Arg 1 to iterparser must be a file object or callable object");
        goto fail;
    }

    PyErr_Clear();

    self->queue_read_idx  = 0;
    self->queue_write_idx = 0;
    self->done            = 0;

    self->text = malloc((size_t)buffersize * sizeof(XML_Char));
    self->text_alloc = buffersize;
    if (self->text == NULL) {
        PyErr_SetString(PyExc_MemoryError, "Out of memory");
        goto fail;
    }
    text_clear(self);

    self->read_args = PyTuple_Pack(1, PyInt_FromSsize_t(buffersize));
    if (self->read_args == NULL) {
        goto fail;
    }

    self->dict_singleton = PyDict_New();
    if (self->dict_singleton == NULL) {
        goto fail;
    }

    self->td_singleton = PyString_FromString("TD");
    if (self->td_singleton == NULL) {
        goto fail;
    }

    self->queue_size = buffersize / 2;
    self->queue = malloc(sizeof(PyObject*) * (size_t)self->queue_size);
    if (self->queue == NULL) {
        PyErr_SetString(PyExc_MemoryError, "Out of memory");
        goto fail;
    }

    /* Set up an expat parser with our callbacks */
    self->parser = XML_ParserCreate(NULL);
    if (self->parser == NULL) {
        PyErr_SetString(PyExc_MemoryError, "Out of memory");
        goto fail;
    }
    XML_SetUserData(self->parser, self);
    XML_SetElementHandler(
        self->parser,
        (XML_StartElementHandler)startElement,
        (XML_EndElementHandler)endElement);
    XML_SetCharacterDataHandler(
        self->parser,
        (XML_CharacterDataHandler)characterData);

    return 0;

 fail:
    Py_XDECREF(self->fd);
    Py_XDECREF(self->read);
    free(self->text);
    Py_XDECREF(self->dict_singleton);
    Py_XDECREF(self->td_singleton);
    Py_XDECREF(self->read_args);
    free(self->queue);

    return -1;
}

static PyMemberDef IterParser_members[] =
{
    {NULL}  /* Sentinel */
};

static PyMethodDef IterParser_methods[] =
{
    {NULL}  /* Sentinel */
};

static PyTypeObject IterParserType =
{
    PyObject_HEAD_INIT(NULL)
#ifndef IS_PY3K
    0,                          /*ob_size*/
#endif
    "IterParser.IterParser",    /*tp_name*/
    sizeof(IterParser),         /*tp_basicsize*/
    0,                          /*tp_itemsize*/
    (destructor)IterParser_dealloc, /*tp_dealloc*/
    0,                          /*tp_print*/
    0,                          /*tp_getattr*/
    0,                          /*tp_setattr*/
    0,                          /*tp_compare*/
    0,                          /*tp_repr*/
    0,                          /*tp_as_number*/
    0,                          /*tp_as_sequence*/
    0,                          /*tp_as_mapping*/
    0,                          /*tp_hash */
    0,                          /*tp_call*/
    0,                          /*tp_str*/
    0,                          /*tp_getattro*/
    0,                          /*tp_setattro*/
    0,                          /*tp_as_buffer*/
    Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE | Py_TPFLAGS_HAVE_GC, /*tp_flags*/
    "IterParser objects",       /* tp_doc */
    (traverseproc)IterParser_traverse, /* tp_traverse */
    (inquiry)IterParser_clear,  /* tp_clear */
    0,                          /* tp_richcompare */
    0,                          /* tp_weaklistoffset */
    (getiterfunc)IterParser_iter, /* tp_iter */
    (iternextfunc)IterParser_next, /* tp_iternext */
    IterParser_methods,         /* tp_methods */
    IterParser_members,         /* tp_members */
    0,                          /* tp_getset */
    0,                          /* tp_base */
    0,                          /* tp_dict */
    0,                          /* tp_descr_get */
    0,                          /* tp_descr_set */
    0,                          /* tp_dictoffset */
    (initproc)IterParser_init,  /* tp_init */
    0,                          /* tp_alloc */
    IterParser_new,             /* tp_new */
};

/******************************************************************************
 * Write TABLEDATA
 ******************************************************************************/

#ifdef IS_PY3K
#  define CHAR Py_UNICODE
#else
#  define CHAR char
#endif

/*
 * Reallocate the write buffer to the requested size
 */
static int
_buffer_realloc(
        CHAR** buffer, Py_ssize_t* buffer_size, CHAR** x, Py_ssize_t req_size)
{
    Py_ssize_t  n       = req_size;
    CHAR *      new_mem = NULL;

    if (req_size < *buffer_size) {
        return 0;
    }

    /* Calculate the next-highest power of two */
    n = next_power_of_2(n);

    if (n < req_size) {
        PyErr_SetString(PyExc_MemoryError, "Out of memory for XML text.");
        return -1;
    }

    new_mem = realloc((void *)*buffer, n * sizeof(CHAR));
    if (new_mem == NULL) {
        PyErr_SetString(PyExc_MemoryError, "Out of memory for XML text.");
        return -1;
    }

    *x = (CHAR *)new_mem + (*x - *buffer);
    *buffer = new_mem;
    *buffer_size = n;

    return 0;
}

/*
 * Write *indent* spaces to the buffer
 */
static int
_write_indent(CHAR** buffer, Py_ssize_t* buffer_size,
              CHAR** x, Py_ssize_t indent)
{
    if (_buffer_realloc(buffer, buffer_size, x,
                        (*x - *buffer + indent))) {
        return 1;
    }

    for (; indent; --indent) {
        *(*x)++ = ' ';
    }

    return 0;
}

/*
 * Write a string into a buffer.  On Python 3 the string and buffer
 * are multibyte
 */
static int
_write_string(CHAR** buffer, Py_ssize_t* buffer_size,
              CHAR** x, const CHAR* src, const Py_ssize_t len) {
    if (_buffer_realloc(buffer, buffer_size, x,
                        (*x - *buffer + len))) {
        return 1;
    }

    while (*src != (CHAR)0) {
        *(*x)++ = *src++;
    }

    return 0;
}

/*
 * Write an 8-bit C string to a possibly Unicode string
 */
static int
_write_cstring(CHAR** buffer, Py_ssize_t* buffer_size,
               CHAR** x, const char* src, const Py_ssize_t len) {
    if (_buffer_realloc(buffer, buffer_size, x,
                        (*x - *buffer + len))) {
        return 1;
    }

    while (*src != (char)0) {
        *(*x)++ = *src++;
    }

    return 0;
}

/*
 * Write a TABLEDATA element tree to the given write method.
 *
 * The Python arguments are:
 *
 * *write_method* (callable): A Python callable that takes a string
 *    (8-bit on Python 2, Unicode on Python 3) and writes it to a file
 *    or buffer.
 *
 * *array* (numpy structured array): A Numpy record array containing
 *    the data
 *
 * *mask* (numpy array): A Numpy array which is True everywhere a
 *    value is missing.  Must have the same shape as *array*.
 *
 * *converters* (list of callables): A sequence of methods which
 *    convert from the native data types in the columns of *array* to
 *    a string in VOTABLE XML format.  Must have the same length as
 *    the number of columns in *array*.
 *
 * *write_null_values* (boolean): When True, write null values in
 *    their entirety in the table.  When False, just write empty <TD/>
 *    elements when the data is null or missing.
 *
 * *indent* (integer): The number of spaces to indent the table.
 *
 * *buf_size* (integer): The size of the write buffer.
 *
 * Returns None.
 */
static PyObject*
write_tabledata(PyObject* self, PyObject *args, PyObject *kwds)
{
    /* Inputs */
    PyObject* write_method = NULL;
    PyObject* array = NULL;
    PyObject* mask = NULL;
    PyObject* converters = NULL;
    int write_null_values = 0;
    Py_ssize_t indent = 0;
    Py_ssize_t buf_size = (Py_ssize_t)1 << 8;

    /* Output buffer */
    CHAR* buf = NULL;
    CHAR* x;

    Py_ssize_t nrows = 0;
    Py_ssize_t ncols = 0;
    Py_ssize_t i, j;
    int write_full;
    int all;
    PyObject* numpy_module = NULL;
    PyObject* numpy_all_method = NULL;
    PyObject* array_row = NULL;
    PyObject* mask_row = NULL;
    PyObject* array_val = NULL;
    PyObject* mask_val = NULL;
    PyObject* converter = NULL;
    PyObject* all_masked_obj = NULL;
    PyObject* str_val = NULL;
    PyObject* tmp = NULL;
    CHAR* str_tmp = NULL;
    Py_ssize_t str_len = 0;
    PyObject* result = 0;

    if (!PyArg_ParseTuple(args, "OOOOinn:write_tabledata",
                          &write_method, &array, &mask, &converters,
                          &write_null_values, &indent, &buf_size)) {
        goto exit;
    }

    if (!PyCallable_Check(write_method)) goto exit;
    if (!PySequence_Check(array)) goto exit;
    if (!PySequence_Check(mask)) goto exit;
    if (!PyList_Check(converters)) goto exit;
    indent = CLAMP(indent, (Py_ssize_t)0, (Py_ssize_t)80);
    buf_size = CLAMP(buf_size, (Py_ssize_t)1 << 8, (Py_ssize_t)1 << 24);

    if ((numpy_module = PyImport_ImportModule("numpy")) == NULL) goto exit;
    if ((numpy_all_method = PyObject_GetAttrString(numpy_module, "all"))
        == NULL) goto exit;

    if ((nrows = PySequence_Size(array)) == -1) goto exit;
    if ((ncols = PyList_Size(converters)) == -1) goto exit;

    if ((buf = malloc((size_t)buf_size * sizeof(CHAR))) == NULL) goto exit;

    for (i = 0; i < nrows; ++i) {
        if ((array_row = PySequence_GetItem(array, i)) == NULL) goto exit;
        if ((mask_row = PySequence_GetItem(mask, i)) == NULL) goto exit;

        x = buf;
        if (_write_indent(&buf, &buf_size, &x, indent)) goto exit;
        if (_write_cstring(&buf, &buf_size, &x, " <TR>\n", 6)) goto exit;

        for (j = 0; j < ncols; ++j) {
            if ((converter = PyList_GET_ITEM(converters, j)) == NULL) goto exit;
            if ((array_val = PySequence_GetItem(array_row, j)) == NULL) goto exit;
            if ((mask_val = PySequence_GetItem(mask_row, j)) == NULL) goto exit;

            if (write_null_values) {
                write_full = 1;
            } else {
                if (mask_val == Py_False) {
                    write_full = 1;
                } else if (mask_val == Py_True) {
                    write_full = 0;
                } else {
                    if ((all_masked_obj =
                         PyObject_CallFunctionObjArgs(numpy_all_method, mask_val, NULL))
                        == NULL) goto exit;
                    if ((all = PyObject_IsTrue(all_masked_obj)) == -1) {
                        Py_DECREF(all_masked_obj);
                        goto exit;
                    }
                    Py_DECREF(all_masked_obj);

                    write_full = !all;
                }
            }

            if (write_full) {
                if (_write_indent(&buf, &buf_size, &x, indent)) goto exit;
                if (_write_cstring(&buf, &buf_size, &x, "  <TD>", 6)) goto exit;

                if ((str_val =
                     PyObject_CallFunctionObjArgs(converter, array_val, mask_val, NULL))
                    == NULL) goto exit;
#ifdef IS_PY3K
                if ((str_tmp = PyUnicode_AsUnicode(str_val)) == NULL) {
                    Py_DECREF(str_val);
                    goto exit;
                }
                str_len = PyUnicode_GetSize(str_val);
#else
                if (PyString_AsStringAndSize(str_val, &str_tmp, &str_len)
                    == -1) {
                    Py_DECREF(str_val);
                    goto exit;
                }
#endif
                if (_write_string(&buf, &buf_size, &x, str_tmp, str_len)) {
                    Py_DECREF(str_val);
                    goto exit;
                }

                Py_DECREF(str_val);

                if (_write_cstring(&buf, &buf_size, &x, "</TD>\n", 6)) goto exit;
            } else {
                if (_write_indent(&buf, &buf_size, &x, indent)) goto exit;
                if (_write_cstring(&buf, &buf_size, &x, "  <TD/>\n", 8)) goto exit;
            }

            Py_DECREF(array_val); array_val = NULL;
            Py_DECREF(mask_val);  mask_val = NULL;
        }

        Py_DECREF(array_row); array_row = NULL;
        Py_DECREF(mask_row);  mask_row = NULL;

        if (_write_indent(&buf, &buf_size, &x, indent)) goto exit;
        if (_write_cstring(&buf, &buf_size, &x, " </TR>\n", 7)) goto exit;

        /* NULL-terminate the string */
        *x = (CHAR)0;
#ifdef IS_PY3K
        if ((tmp = PyObject_CallFunction(write_method, "u#", buf, x - buf))
            == NULL) goto exit;
#else
        if ((tmp = PyObject_CallFunction(write_method, "s#", buf, x - buf))
            == NULL) goto exit;
#endif
        Py_DECREF(tmp);
    }

    Py_INCREF(Py_None);
    result = Py_None;

 exit:
    Py_XDECREF(numpy_module);
    Py_XDECREF(numpy_all_method);

    Py_XDECREF(array_row);
    Py_XDECREF(mask_row);
    Py_XDECREF(array_val);
    Py_XDECREF(mask_val);

    free(buf);

    return result;
}

/******************************************************************************
 * XML escaping
 ******************************************************************************/

/* These are in reverse order by input character */
static const char* escapes_cdata[] = {
    ">", "&gt;",
    "<", "&lt;",
    "&", "&amp;",
    "\0", "\0",
};

/* These are in reverse order by input character */
static const char* escapes[] = {
    ">", "&gt;",
    "<", "&lt;",
    "'", "&apos;",
    "&", "&amp;",
    "\"", "&quot;",
    "\0", "\0"
};

/*
 * Returns a copy of the given string (8-bit or Unicode) with the XML
 * control characters converted to XML character entities.
 *
 * If an 8-bit string is passed in, an 8-bit string is returned.  If a
 * Unicode string is passed in, a Unicode string is returned.
 */
static PyObject*
_escape_xml(PyObject* self, PyObject *args, PyObject *kwds,
            const char** escapes)
{
    PyObject* input_obj;
    PyObject* output_obj;
    int count = 0;
    Py_UNICODE* uinput = NULL;
    char* input = NULL;
    Py_ssize_t input_len;
    Py_UNICODE* uoutput = NULL;
    char* output = NULL;
    Py_UNICODE* up = NULL;
    char* p = NULL;
    Py_ssize_t i;
    const char** esc;
    const char* ent;

    if (!PyArg_ParseTuple(args, "O:escape_xml", &input_obj)) {
        return NULL;
    }

    if (PyUnicode_Check(input_obj)) {
        uinput = PyUnicode_AsUnicode(input_obj);
        if (uinput == NULL) {
            return NULL;
        }

        input_len = PyUnicode_GetSize(input_obj);

        for (i = 0; i < input_len; ++i) {
            for (esc = escapes; ; esc += 2) {
                if (uinput[i] > (Py_UNICODE)**esc) {
                    break;
                } else if (uinput[i] == (Py_UNICODE)**esc) {
                    ++count;
                    break;
                }
            }
        }

        if (count) {
            uoutput = malloc((input_len + 1 + count * 5) * sizeof(Py_UNICODE));
            if (uoutput == NULL) {
                PyErr_SetString(PyExc_MemoryError, "Out of memory");
                return NULL;
            }

            up = uoutput;
            for (i = 0; i < input_len; ++i) {
                for (esc = escapes; ; esc += 2) {
                    if (uinput[i] > (Py_UNICODE)**esc) {
                        *(up++) = uinput[i];
                        break;
                    } else if (uinput[i] == (Py_UNICODE)**esc) {
                        for (ent = *(esc + 1); *ent != '\0'; ++ent) {
                            *(up++) = (Py_UNICODE)*ent;
                        }
                        break;
                    }
                }
            }

            *up = 0;

            output_obj = PyUnicode_FromUnicode(uoutput, up - uoutput);
            free(uoutput);
            return output_obj;
        }
    } else if (PyBytes_Check(input_obj)) {
        if (PyBytes_AsStringAndSize(input_obj, &input, &input_len) == -1) {
            return NULL;
        }

        for (i = 0; i < input_len; ++i) {
            for (esc = escapes; ; esc += 2) {
                if (input[i] > **esc) {
                    break;
                } else if (input[i] == **esc) {
                    ++count;
                    break;
                }
            }
        }

        if (count) {
            output = malloc((input_len + 1 + count * 5) * sizeof(char));
            if (output == NULL) {
                PyErr_SetString(PyExc_MemoryError, "Out of memory");
                return NULL;
            }

            p = output;
            for (i = 0; i < input_len; ++i) {
                for (esc = escapes; ; esc += 2) {
                    if (input[i] > **esc) {
                        *(p++) = input[i];
                        break;
                    } else if (input[i] == **esc) {
                        for (ent = *(esc + 1); *ent != '\0'; ++ent) {
                            *(p++) = *ent;
                        }
                        break;
                    }
                }
            }

            *p = 0;

            output_obj = PyBytes_FromStringAndSize(output, p - output);
            free(output);
            return output_obj;
        }
    } else {
        #ifdef IS_PY3K
        PyErr_SetString(PyExc_TypeError, "must be str or bytes");
        #else
        PyErr_SetString(PyExc_TypeError, "must be str or unicode");
        #endif
        return NULL;
    }

    Py_INCREF(input_obj);
    return input_obj;
}

static PyObject*
escape_xml(PyObject* self, PyObject *args, PyObject *kwds)
{
    return _escape_xml(self, args, kwds, escapes);
}

static PyObject*
escape_xml_cdata(PyObject* self, PyObject *args, PyObject *kwds)
{
    return _escape_xml(self, args, kwds, escapes_cdata);
}

/******************************************************************************
 * Module setup
 ******************************************************************************/

static PyMethodDef module_methods[] =
{
    {"write_tabledata", (PyCFunction)write_tabledata, METH_VARARGS,
     "Fast C method to write tabledata"},
    {"escape_xml", (PyCFunction)escape_xml, METH_VARARGS,
     "Fast method to escape XML strings"},
    {"escape_xml_cdata", (PyCFunction)escape_xml_cdata, METH_VARARGS,
     "Fast method to escape XML strings"},
    {NULL}  /* Sentinel */
};

struct module_state {
    void* none;
};

#ifdef IS_PY3K
static int module_traverse(PyObject* m, visitproc visit, void* arg)
{
    return 0;
}

static int module_clear(PyObject* m)
{
    return 0;
}

static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,
    "iterparser",
    "Fast XML parser",
    sizeof(struct module_state),
    module_methods,
    NULL,
    module_traverse,
    module_clear,
    NULL
};

#  define INITERROR return NULL

PyMODINIT_FUNC
PyInit_iterparser(void)
#else /* Not PY3K */
#  define INITERROR return

#  ifndef PyMODINIT_FUNC  /* declarations for DLL import/export */
#    define PyMODINIT_FUNC void
#  endif

PyMODINIT_FUNC
inititerparser(void)
#endif
{
    PyObject* m;

#ifdef IS_PY3K
    m = PyModule_Create(&moduledef);
#else
    m = Py_InitModule3("iterparser", module_methods, "Fast XML parser");
#endif

    if (PyType_Ready(&IterParserType) < 0)
        INITERROR;

    if (m == NULL)
        INITERROR;

    Py_INCREF(&IterParserType);
    PyModule_AddObject(m, "IterParser", (PyObject *)&IterParserType);

#ifdef IS_PY3K
    return m;
#endif
}
