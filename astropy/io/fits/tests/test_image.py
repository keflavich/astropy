# Licensed under a 3-clause BSD style license - see PYFITS.rst

import os
import warnings

import numpy as np

from ....io import fits
from ....tests.helper import pytest, raises

from . import FitsTestCase


class TestImageFunctions(FitsTestCase):
    def test_constructor_name_arg(self):
        """Like the test of the same name in test_table.py"""

        hdu = fits.ImageHDU()
        assert hdu.name == ''
        assert 'EXTNAME' not in hdu.header
        hdu.name = 'FOO'
        assert hdu.name == 'FOO'
        assert hdu.header['EXTNAME'] == 'FOO'

        # Passing name to constructor
        hdu = fits.ImageHDU(name='FOO')
        assert hdu.name == 'FOO'
        assert hdu.header['EXTNAME'] == 'FOO'

        # And overriding a header with a different extname
        hdr = fits.Header()
        hdr['EXTNAME'] = 'EVENTS'
        hdu = fits.ImageHDU(header=hdr, name='FOO')
        assert hdu.name == 'FOO'
        assert hdu.header['EXTNAME'] == 'FOO'

    @raises(ValueError)
    def test_open(self):
        # The function "open" reads a FITS file into an HDUList object.  There
        # are three modes to open: "readonly" (the default), "append", and
        # "update".

        # Open a file read-only (the default mode), the content of the FITS
        # file are read into memory.
        r = fits.open(self.data('test0.fits')) # readonly

        # data parts are latent instantiation, so if we close the HDUList
        # without touching data, data can not be accessed.
        r.close()
        r[1].data[:2,:2]

    def test_open_2(self):
        r = fits.open(self.data('test0.fits'))

        info = [(0, 'PRIMARY', 'PrimaryHDU', 138, (), 'int16', '')] + \
               [(x, 'SCI', 'ImageHDU', 61, (40, 40), 'int16', '')
                for x in range(1, 5)]

        try:
            assert r.info(output=False) == info
        finally:
            r.close()

    def test_io_manipulation(self):
        # Get a keyword value.  An extension can be referred by name or by
        # number.  Both extension and keyword names are case insensitive.
        r = fits.open(self.data('test0.fits'))
        assert r['primary'].header['naxis'] == 0
        assert r[0].header['naxis'] == 0

        # If there are more than one extension with the same EXTNAME value, the
        # EXTVER can be used (as the second argument) to distinguish the
        # extension.
        assert r['sci',1].header['detector'] == 1

        # append (using "update()") a new card
        r[0].header['xxx'] = 1.234e56

        if str(r[0].header.ascard[-3:]) != \
           "EXPFLAG = 'NORMAL            ' / Exposure interruption indicator                \n" \
           "FILENAME= 'vtest3.fits'        / File name                                      \n" \
           "XXX     =            1.234E+56                                                  " and \
           str(r[0].header.ascard[-3:]) != \
           "EXPFLAG = 'NORMAL            ' / Exposure interruption indicator                \n" \
           "FILENAME= 'vtest3.fits'        / File name                                      \n" \
           "XXX     =           1.234E+056                                                  ":
            assert (str(r[0].header.ascard[-3:]) ==
                    "EXPFLAG = 'NORMAL            ' / Exposure interruption indicator                \n"
                    "FILENAME= 'vtest3.fits'        / File name                                      \n"
                    "XXX     =            1.234E+56                                                  ")

        # rename a keyword
        r[0].header.rename_key('filename', 'fname')
        pytest.raises(ValueError, r[0].header.rename_key, 'fname', 'history')

        pytest.raises(ValueError, r[0].header.rename_key, 'fname', 'simple')
        r[0].header.rename_key('fname', 'filename')

        # get a subsection of data
        assert (r[2].data[:3,:3] ==
                np.array([[349, 349, 348],
                          [349, 349, 347],
                          [347, 350, 349]], dtype=np.int16)).all()

        # We can create a new FITS file by opening a new file with "append"
        # mode.
        n=fits.open(self.temp('test_new.fits'), mode='append')

        # Append the primary header and the 2nd extension to the new file.
        n.append(r[0])
        n.append(r[2])

        # The flush method will write the current HDUList object back to the
        # newly created file on disk.  The HDUList is still open and can be
        # further operated.
        n.flush()
        assert n[1].data[1,1] == 349

        #modify a data point
        n[1].data[1,1] = 99

        # When the file is closed, the most recent additions of extension(s)
        # since last flush() will be appended, but any HDU already existed at
        # the last flush will not be modified
        n.close()

        # If an existing file is opened with "append" mode, like the readonly
        # mode, the HDU's will be read into the HDUList which can be modified
        # in memory but can not be written back to the original file.  A file
        # opened with append mode can only add new HDU's.
        os.rename(self.temp('test_new.fits'), self.temp('test_append.fits'))
        a = fits.open(self.temp('test_append.fits'), mode='append')

        # The above change did not take effect since this was made after the
        # flush().
        assert a[1].data[1,1] == 349

        a.append(r[1])
        a.close()

        # When changes are made to an HDUList which was opened with "update"
        # mode, they will be written back to the original file when a
        # flush/close is called.
        os.rename(self.temp('test_append.fits'), self.temp('test_update.fits'))

        u = fits.open(self.temp('test_update.fits'), mode='update')

        # When the changes do not alter the size structures of the original (or
        # since last flush) HDUList, the changes are written back "in place".
        assert u[0].header['rootname'] == 'U2EQ0201T'
        u[0].header['rootname'] = 'abc'
        assert u[1].data[1,1] == 349
        u[1].data[1,1] = 99
        u.flush()

        # If the changes affect the size structure, e.g. adding or deleting
        # HDU(s), header was expanded or reduced beyond existing number of
        # blocks (2880 bytes in each block), or change the data size, the
        # HDUList is written to a temporary file, the original file is deleted,
        # and the temporary file is renamed to the original file name and
        # reopened in the update mode.
        # To a user, these two kinds of updating writeback seem to be the same,
        # unless the optional argument in flush or close is set to 1.
        del u[2]
        u.flush()

        # the write method in HDUList class writes the current HDUList, with
        # all changes made up to now, to a new file.  This method works the
        # same disregard the mode the HDUList was opened with.
        u.append(r[3])
        u.writeto(self.temp('test_new.fits'))

        # Remove temporary files created by this test
        u.close()


        #Another useful new HDUList method is readall.  It will "touch" the
        # data parts in all HDUs, so even if the HDUList is closed, we can
        # still operate on the data.
        r = fits.open(self.data('test0.fits'))
        r.readall()
        r.close()
        assert r[1].data[1,1] == 315

        # create an HDU with data only
        data = np.ones((3,5), dtype=np.float32)
        hdu = fits.ImageHDU(data=data, name='SCI')
        assert (hdu.data ==
                np.array([[ 1.,  1.,  1.,  1.,  1.],
                          [ 1.,  1.,  1.,  1.,  1.],
                          [ 1.,  1.,  1.,  1.,  1.]], dtype=np.float32)).all()


        # create an HDU with header and data
        # notice that the header has the right NAXIS's since it is constructed
        # with ImageHDU
        hdu2 = fits.ImageHDU(header=r[1].header, data=np.array([1,2],
                               dtype='int32'))

        assert (str(hdu2.header.ascard[1:5]) ==
                "BITPIX  =                   32 / array data type                                \n"
                "NAXIS   =                    1 / number of array dimensions                     \n"
                "NAXIS1  =                    2                                                  \n"
               "PCOUNT  =                    0 / number of parameters                           ")

    def test_memory_mapping(self):
        # memory mapping
        f1 = fits.open(self.data('test0.fits'), memmap=1)
        f1.close()

    def test_verification_on_output(self):
        # verification on output
        # make a defect HDUList first
        x = fits.ImageHDU()
        hdu = fits.HDUList(x)  # HDUList can take a list or one single HDU
        with warnings.catch_warnings(record=True) as w:
            hdu.verify()
            text = "HDUList's 0th element is not a primary HDU."
            assert len(w) == 1
            assert text in str(w[0].message)

            hdu.writeto(self.temp('test_new2.fits'), 'fix')
            text = ("HDUList's 0th element is not a primary HDU.  "
                    "Fixed by inserting one as 0th HDU.")
            assert len(w) == 2
            assert text in str(w[1].message)

    def test_section(self):
        # section testing
        fs = fits.open(self.data('arange.fits'))
        assert fs[0].section[3,2,5] == np.array([357])
        assert (fs[0].section[3,2,:] ==
                np.array([352, 353, 354, 355, 356, 357, 358, 359, 360, 361,
                          362])).all()
        assert (fs[0].section[3,2,4:] ==
                np.array([356, 357, 358, 359, 360, 361, 362])).all()
        assert (fs[0].section[3,2,:8] ==
                np.array([352, 353, 354, 355, 356, 357, 358, 359])).all()
        assert (fs[0].section[3,2,-8:8] ==
                np.array([355, 356, 357, 358, 359])).all()
        assert (fs[0].section[3,2:5,:] ==
                np.array([[352, 353, 354, 355, 356, 357, 358, 359, 360, 361,
                           362],
                          [363, 364, 365, 366, 367, 368, 369, 370, 371, 372,
                           373],
                          [374, 375, 376, 377, 378, 379, 380, 381, 382, 383,
                           384]])).all()

        assert (fs[0].section[3,:,:][:3,:3] ==
                np.array([[330, 331, 332],
                          [341, 342, 343],
                          [352, 353, 354]])).all()

        dat = fs[0].data
        assert (fs[0].section[3,2:5,:8] == dat[3,2:5,:8]).all()
        assert (fs[0].section[3,2:5,3] == dat[3,2:5,3]).all()

        assert (fs[0].section[3:6,:,:][:3,:3,:3] ==
                np.array([[[330, 331, 332],
                           [341, 342, 343],
                           [352, 353, 354]],
                          [[440, 441, 442],
                           [451, 452, 453],
                           [462, 463, 464]],
                          [[550, 551, 552],
                           [561, 562, 563],
                           [572, 573, 574]]])).all()

        assert (fs[0].section[:,:,:][:3,:2,:2] ==
                np.array([[[  0,   1],
                           [ 11,  12]],
                          [[110, 111],
                           [121, 122]],
                          [[220, 221],
                           [231, 232]]])).all()

        assert (fs[0].section[:,2,:] == dat[:,2,:]).all()
        assert (fs[0].section[:,2:5,:] == dat[:,2:5,:]).all()
        assert (fs[0].section[3:6,3,:] == dat[3:6,3,:]).all()
        assert (fs[0].section[3:6,3:7,:] == dat[3:6,3:7,:]).all()

    def test_section_data_square(self):
        a = np.arange(4).reshape((2, 2))
        hdu = fits.PrimaryHDU(a)
        hdu.writeto(self.temp('test_new.fits'))

        hdul = fits.open(self.temp('test_new.fits'))
        d = hdul[0]
        dat = hdul[0].data
        assert (d.section[:,:] == dat[:,:]).all()
        assert (d.section[0,:] == dat[0,:]).all()
        assert (d.section[1,:] == dat[1,:]).all()
        assert (d.section[:,0] == dat[:,0]).all()
        assert (d.section[:,1] == dat[:,1]).all()
        assert (d.section[0,0] == dat[0,0]).all()
        assert (d.section[0,1] == dat[0,1]).all()
        assert (d.section[1,0] == dat[1,0]).all()
        assert (d.section[1,1] == dat[1,1]).all()
        assert (d.section[0:1,0:1] == dat[0:1,0:1]).all()
        assert (d.section[0:2,0:1] == dat[0:2,0:1]).all()
        assert (d.section[0:1,0:2] == dat[0:1,0:2]).all()
        assert (d.section[0:2,0:2] == dat[0:2,0:2]).all()

    def test_section_data_cube(self):
        a=np.arange(18).reshape((2,3,3))
        hdu = fits.PrimaryHDU(a)
        hdu.writeto(self.temp('test_new.fits'))

        hdul=fits.open(self.temp('test_new.fits'))
        d = hdul[0]
        dat = hdul[0].data
        assert (d.section[:,:,:] == dat[:,:,:]).all()
        assert (d.section[:,:] == dat[:,:]).all()
        assert d.section[:].all() == dat[:].all()
        assert (d.section[0,:,:] == dat[0,:,:]).all()
        assert (d.section[1,:,:] == dat[1,:,:]).all()
        assert (d.section[0,0,:] == dat[0,0,:]).all()
        assert (d.section[0,1,:] == dat[0,1,:]).all()
        assert (d.section[0,2,:] == dat[0,2,:]).all()
        assert (d.section[1,0,:] == dat[1,0,:]).all()
        assert (d.section[1,1,:] == dat[1,1,:]).all()
        assert (d.section[1,2,:] == dat[1,2,:]).all()
        assert (d.section[0,0,0] == dat[0,0,0]).all()
        assert (d.section[0,0,1] == dat[0,0,1]).all()
        assert (d.section[0,0,2] == dat[0,0,2]).all()
        assert (d.section[0,1,0] == dat[0,1,0]).all()
        assert (d.section[0,1,1] == dat[0,1,1]).all()
        assert (d.section[0,1,2] == dat[0,1,2]).all()
        assert (d.section[0,2,0] == dat[0,2,0]).all()
        assert (d.section[0,2,1] == dat[0,2,1]).all()
        assert (d.section[0,2,2] == dat[0,2,2]).all()
        assert (d.section[1,0,0] == dat[1,0,0]).all()
        assert (d.section[1,0,1] == dat[1,0,1]).all()
        assert (d.section[1,0,2] == dat[1,0,2]).all()
        assert (d.section[1,1,0] == dat[1,1,0]).all()
        assert (d.section[1,1,1] == dat[1,1,1]).all()
        assert (d.section[1,1,2] == dat[1,1,2]).all()
        assert (d.section[1,2,0] == dat[1,2,0]).all()
        assert (d.section[1,2,1] == dat[1,2,1]).all()
        assert (d.section[1,2,2] == dat[1,2,2]).all()
        assert (d.section[:,0,0] == dat[:,0,0]).all()
        assert (d.section[:,0,1] == dat[:,0,1]).all()
        assert (d.section[:,0,2] == dat[:,0,2]).all()
        assert (d.section[:,1,0] == dat[:,1,0]).all()
        assert (d.section[:,1,1] == dat[:,1,1]).all()
        assert (d.section[:,1,2] == dat[:,1,2]).all()
        assert (d.section[:,2,0] == dat[:,2,0]).all()
        assert (d.section[:,2,1] == dat[:,2,1]).all()
        assert (d.section[:,2,2] == dat[:,2,2]).all()
        assert (d.section[0,:,0] == dat[0,:,0]).all()
        assert (d.section[0,:,1] == dat[0,:,1]).all()
        assert (d.section[0,:,2] == dat[0,:,2]).all()
        assert (d.section[1,:,0] == dat[1,:,0]).all()
        assert (d.section[1,:,1] == dat[1,:,1]).all()
        assert (d.section[1,:,2] == dat[1,:,2]).all()
        assert (d.section[:,:,0] == dat[:,:,0]).all()
        assert (d.section[:,:,1] == dat[:,:,1]).all()
        assert (d.section[:,:,2] == dat[:,:,2]).all()
        assert (d.section[:,0,:] == dat[:,0,:]).all()
        assert (d.section[:,1,:] == dat[:,1,:]).all()
        assert (d.section[:,2,:] == dat[:,2,:]).all()

        assert (d.section[:,:,0:1] == dat[:,:,0:1]).all()
        assert (d.section[:,:,0:2] == dat[:,:,0:2]).all()
        assert (d.section[:,:,0:3] == dat[:,:,0:3]).all()
        assert (d.section[:,:,1:2] == dat[:,:,1:2]).all()
        assert (d.section[:,:,1:3] == dat[:,:,1:3]).all()
        assert (d.section[:,:,2:3] == dat[:,:,2:3]).all()
        assert (d.section[0:1,0:1,0:1] == dat[0:1,0:1,0:1]).all()
        assert (d.section[0:1,0:1,0:2] == dat[0:1,0:1,0:2]).all()
        assert (d.section[0:1,0:1,0:3] == dat[0:1,0:1,0:3]).all()
        assert (d.section[0:1,0:1,1:2] == dat[0:1,0:1,1:2]).all()
        assert (d.section[0:1,0:1,1:3] == dat[0:1,0:1,1:3]).all()
        assert (d.section[0:1,0:1,2:3] == dat[0:1,0:1,2:3]).all()
        assert (d.section[0:1,0:2,0:1] == dat[0:1,0:2,0:1]).all()
        assert (d.section[0:1,0:2,0:2] == dat[0:1,0:2,0:2]).all()
        assert (d.section[0:1,0:2,0:3] == dat[0:1,0:2,0:3]).all()
        assert (d.section[0:1,0:2,1:2] == dat[0:1,0:2,1:2]).all()
        assert (d.section[0:1,0:2,1:3] == dat[0:1,0:2,1:3]).all()
        assert (d.section[0:1,0:2,2:3] == dat[0:1,0:2,2:3]).all()
        assert (d.section[0:1,0:3,0:1] == dat[0:1,0:3,0:1]).all()
        assert (d.section[0:1,0:3,0:2] == dat[0:1,0:3,0:2]).all()
        assert (d.section[0:1,0:3,0:3] == dat[0:1,0:3,0:3]).all()
        assert (d.section[0:1,0:3,1:2] == dat[0:1,0:3,1:2]).all()
        assert (d.section[0:1,0:3,1:3] == dat[0:1,0:3,1:3]).all()
        assert (d.section[0:1,0:3,2:3] == dat[0:1,0:3,2:3]).all()
        assert (d.section[0:1,1:2,0:1] == dat[0:1,1:2,0:1]).all()
        assert (d.section[0:1,1:2,0:2] == dat[0:1,1:2,0:2]).all()
        assert (d.section[0:1,1:2,0:3] == dat[0:1,1:2,0:3]).all()
        assert (d.section[0:1,1:2,1:2] == dat[0:1,1:2,1:2]).all()
        assert (d.section[0:1,1:2,1:3] == dat[0:1,1:2,1:3]).all()
        assert (d.section[0:1,1:2,2:3] == dat[0:1,1:2,2:3]).all()
        assert (d.section[0:1,1:3,0:1] == dat[0:1,1:3,0:1]).all()
        assert (d.section[0:1,1:3,0:2] == dat[0:1,1:3,0:2]).all()
        assert (d.section[0:1,1:3,0:3] == dat[0:1,1:3,0:3]).all()
        assert (d.section[0:1,1:3,1:2] == dat[0:1,1:3,1:2]).all()
        assert (d.section[0:1,1:3,1:3] == dat[0:1,1:3,1:3]).all()
        assert (d.section[0:1,1:3,2:3] == dat[0:1,1:3,2:3]).all()
        assert (d.section[1:2,0:1,0:1] == dat[1:2,0:1,0:1]).all()
        assert (d.section[1:2,0:1,0:2] == dat[1:2,0:1,0:2]).all()
        assert (d.section[1:2,0:1,0:3] == dat[1:2,0:1,0:3]).all()
        assert (d.section[1:2,0:1,1:2] == dat[1:2,0:1,1:2]).all()
        assert (d.section[1:2,0:1,1:3] == dat[1:2,0:1,1:3]).all()
        assert (d.section[1:2,0:1,2:3] == dat[1:2,0:1,2:3]).all()
        assert (d.section[1:2,0:2,0:1] == dat[1:2,0:2,0:1]).all()
        assert (d.section[1:2,0:2,0:2] == dat[1:2,0:2,0:2]).all()
        assert (d.section[1:2,0:2,0:3] == dat[1:2,0:2,0:3]).all()
        assert (d.section[1:2,0:2,1:2] == dat[1:2,0:2,1:2]).all()
        assert (d.section[1:2,0:2,1:3] == dat[1:2,0:2,1:3]).all()
        assert (d.section[1:2,0:2,2:3] == dat[1:2,0:2,2:3]).all()
        assert (d.section[1:2,0:3,0:1] == dat[1:2,0:3,0:1]).all()
        assert (d.section[1:2,0:3,0:2] == dat[1:2,0:3,0:2]).all()
        assert (d.section[1:2,0:3,0:3] == dat[1:2,0:3,0:3]).all()
        assert (d.section[1:2,0:3,1:2] == dat[1:2,0:3,1:2]).all()
        assert (d.section[1:2,0:3,1:3] == dat[1:2,0:3,1:3]).all()
        assert (d.section[1:2,0:3,2:3] == dat[1:2,0:3,2:3]).all()
        assert (d.section[1:2,1:2,0:1] == dat[1:2,1:2,0:1]).all()
        assert (d.section[1:2,1:2,0:2] == dat[1:2,1:2,0:2]).all()
        assert (d.section[1:2,1:2,0:3] == dat[1:2,1:2,0:3]).all()
        assert (d.section[1:2,1:2,1:2] == dat[1:2,1:2,1:2]).all()
        assert (d.section[1:2,1:2,1:3] == dat[1:2,1:2,1:3]).all()
        assert (d.section[1:2,1:2,2:3] == dat[1:2,1:2,2:3]).all()
        assert (d.section[1:2,1:3,0:1] == dat[1:2,1:3,0:1]).all()
        assert (d.section[1:2,1:3,0:2] == dat[1:2,1:3,0:2]).all()
        assert (d.section[1:2,1:3,0:3] == dat[1:2,1:3,0:3]).all()
        assert (d.section[1:2,1:3,1:2] == dat[1:2,1:3,1:2]).all()
        assert (d.section[1:2,1:3,1:3] == dat[1:2,1:3,1:3]).all()
        assert (d.section[1:2,1:3,2:3] == dat[1:2,1:3,2:3]).all()

    def test_section_data_four(self):
        a = np.arange(256).reshape((4, 4, 4, 4))
        hdu = fits.PrimaryHDU(a)
        hdu.writeto(self.temp('test_new.fits'))

        hdul=fits.open(self.temp('test_new.fits'))
        d=hdul[0]
        dat = hdul[0].data
        assert (d.section[:,:,:,:] == dat[:,:,:,:]).all()
        assert (d.section[:,:,:] == dat[:,:,:]).all()
        assert (d.section[:,:] == dat[:,:]).all()
        assert d.section[:].all() == dat[:].all()
        assert (d.section[0,:,:,:] == dat[0,:,:,:]).all()
        assert (d.section[0,:,0,:] == dat[0,:,0,:]).all()
        assert (d.section[:,:,0,:] == dat[:,:,0,:]).all()
        assert (d.section[:,1,0,:] == dat[:,1,0,:]).all()
        assert (d.section[:,:,:,1] == dat[:,:,:,1]).all()

    def test_comp_image(self):
        def _test_comp_image(self, data, compression_type, quantize_level,
                             byte_order):
            self.setup()
            try:
                data = data.newbyteorder(byte_order)
                primary_hdu = fits.PrimaryHDU()
                ofd = fits.HDUList(primary_hdu)
                chdu = fits.CompImageHDU(data, name='SCI',
                                         compressionType=compression_type,
                                         quantizeLevel=quantize_level)
                ofd.append(chdu)
                ofd.writeto(self.temp('test_new.fits'), clobber=True)
                ofd.close()
                fd = fits.open(self.temp('test_new.fits'))
                assert fd[1].data.all() == data.all()
                assert fd[1].header['NAXIS'] == chdu.header['NAXIS']
                assert fd[1].header['NAXIS1'] == chdu.header['NAXIS1']
                assert fd[1].header['NAXIS2'] == chdu.header['NAXIS2']
                assert fd[1].header['BITPIX'] == chdu.header['BITPIX']
                fd.close()
            finally:
                self.teardown()

        argslist = [
            (np.zeros((2, 10, 10), dtype=np.float32), 'RICE_1', 16),
            (np.zeros((2, 10, 10), dtype=np.float32), 'GZIP_1', -0.01),
            (np.zeros((100, 100)) + 1, 'HCOMPRESS_1', 16)
        ]

        for byte_order in ('<', '>'):
            for args in argslist:
                yield (_test_comp_image, self) + args + (byte_order,)

    def test_comp_image_hcompression_1_invalid_data(self):
        """
        Tests compression with the HCOMPRESS_1 algorithm with data that is
        not 2D (and thus should not work).
        """

        pytest.raises(ValueError, fits.CompImageHDU,
                      np.zeros((2, 10, 10), dtype=np.float32), name='SCI',
                      compressionType='HCOMPRESS_1', quantizeLevel=16)

    def test_disable_image_compression(self):
        with warnings.catch_warnings():
            # No warnings should be displayed in this case
            warnings.simplefilter('error')
            hdul = fits.open(self.data('comp.fits'),
                               disable_image_compression=True)
            # The compressed image HDU should show up as a BinTableHDU, but
            # *not* a CompImageHDU
            assert isinstance(hdul[1], fits.BinTableHDU)
            assert not isinstance(hdul[1], fits.CompImageHDU)

    def test_do_not_scale_image_data(self):
        hdul = fits.open(self.data('scale.fits'),
                           do_not_scale_image_data=True)
        assert hdul[0].data.dtype == np.dtype('>i2')
        hdul = fits.open(self.data('scale.fits'))
        assert hdul[0].data.dtype == np.dtype('float32')

    def test_append_uint_data(self):
        """Test for ticket #56 (BZERO and BSCALE added in the wrong location
        when appending scaled data)
        """

        fits.writeto(self.temp('test_new.fits'), data=np.array([],
                       dtype='uint8'))
        d = np.zeros([100, 100]).astype('uint16')
        fits.append(self.temp('test_new.fits'), data=d)
        f = fits.open(self.temp('test_new.fits'), uint=True)
        assert f[1].data.dtype == 'uint16'

    def test_blanks(self):
        """Test image data with blank spots in it (which should show up as
        NaNs in the data array.
        """

        arr = np.zeros((10, 10), dtype=np.int32)
        # One row will be blanks
        arr[1] = 999
        hdu = fits.ImageHDU(data=arr)
        hdu.header['BLANK'] = 999
        hdu.writeto(self.temp('test_new.fits'))

        hdul = fits.open(self.temp('test_new.fits'))
        assert np.isnan(hdul[1].data[1]).all()

    def test_bzero_with_floats(self):
        """Test use of the BZERO keyword in an image HDU containing float
        data.
        """

        arr = np.zeros((10, 10)) - 1
        hdu = fits.ImageHDU(data=arr)
        hdu.header['BZERO'] = 1.0
        hdu.writeto(self.temp('test_new.fits'))

        hdul = fits.open(self.temp('test_new.fits'))
        arr += 1
        assert (hdul[1].data == arr).all()

    def test_rewriting_large_scaled_image(self):
        """Regression test for #84"""

        hdul = fits.open(self.data('fixed-1890.fits'))
        orig_data = hdul[0].data
        hdul.writeto(self.temp('test_new.fits'), clobber=True)
        hdul.close()
        hdul = fits.open(self.temp('test_new.fits'))
        assert (hdul[0].data == orig_data).all()
        hdul.close()

        # Just as before, but this time don't touch hdul[0].data before writing
        # back out--this is the case that failed in #84
        hdul = fits.open(self.data('fixed-1890.fits'))
        hdul.writeto(self.temp('test_new.fits'), clobber=True)
        hdul.close()
        hdul = fits.open(self.temp('test_new.fits'))
        assert (hdul[0].data == orig_data).all()
        hdul.close()

        # Test opening/closing/reopening a scaled file in update mode
        hdul = fits.open(self.data('fixed-1890.fits'),
                           do_not_scale_image_data=True)
        hdul.writeto(self.temp('test_new.fits'), clobber=True,
                     output_verify='silentfix')
        hdul.close()
        hdul = fits.open(self.temp('test_new.fits'))
        orig_data = hdul[0].data
        hdul.close()
        hdul = fits.open(self.temp('test_new.fits'), mode='update')
        hdul.close()
        hdul = fits.open(self.temp('test_new.fits'))
        assert (hdul[0].data == orig_data).all()
        hdul = fits.open(self.temp('test_new.fits'))
        hdul.close()
