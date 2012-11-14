from distutils import version
import numpy as np

from ...tests.helper import pytest
from ... import table

numpy_lt_1p5 = version.LooseVersion(np.__version__) < version.LooseVersion('1.5')

# Fixture to run all the Column tests for both an unmasked (ndarray)
# and masked (MaskedArray) column.
@pytest.fixture(params=[table.Column] if numpy_lt_1p5 else [table.Column, table.MaskedColumn])
def Column(request):
    return request.param


class TestColumn():

    def test_1(self, Column):
        Column('a')

    def test_subclass(self, Column):
        c = Column('a')
        assert isinstance(c, np.ndarray)
        c2 = c * 2
        assert isinstance(c2, Column)
        assert isinstance(c2, np.ndarray)

    def test_numpy_ops(self, Column):
        """Show that basic numpy operations with Column behave sensibly"""

        arr = np.array([1, 2, 3])
        c = Column('a', arr)
        eq = c == arr
        assert np.all(eq)
        assert len(eq) == 3
        assert type(eq) == Column
        assert eq.dtype.str == '|b1'
        eq = arr == c
        assert np.all(eq)

        lt = c - 1 < arr
        assert np.all(lt)

    def test_view(self, Column):
        c = np.array([1, 2, 3]).view(Column)
        if Column == table.MaskedColumn:
            assert repr(c) == ('masked_array(data = [1 2 3],\n'
                               '             mask = False,\n'
                               '       fill_value = 999999)\n')
        else:
            assert repr(c) == 'array([1, 2, 3])'

    def test_format(self, Column):
        """Show that the formatted output from str() works"""
        MAX_LINES_val = table.pprint.MAX_LINES()
        table.pprint.MAX_LINES.set(7)
        c1 = Column(name='a', data=np.arange(2000), dtype=float,
                    format='%6.2f')
        assert str(c1) == ('   a   \n-------\n   0.00\n'
                           '   1.00\n    ...\n1998.00\n1999.00')
        table.pprint.MAX_LINES.set(MAX_LINES_val)

    def test_convert_numpy_array(self, Column):
        d = Column('a', [1, 2, 3], dtype='i8')

        np_data = np.array(d)
        assert np.all(np_data == d)
        np_data = np.array(d, copy=False)
        assert np.all(np_data == d)
        np_data = np.array(d, dtype='i4')
        assert np.all(np_data == d)

    def test_convert_units(self, Column):
        d = Column('a', [1, 2, 3], dtype="f8", units="m")
        d.convert_units_to("km")
        assert np.all(d.data == [0.001, 0.002, 0.003])


class TestAttrEqual():
    """Bunch of tests originally from ATpy that test the attrs_equal method."""

    def test_5(self, Column):
        c1 = Column(name='a', dtype=int, units='mJy')
        c2 = Column(name='a', dtype=int, units='mJy')
        assert c1.attrs_equal(c2)

    def test_6(self, Column):
        c1 = Column(name='a', dtype=int, units='mJy', format='%i',
                    description='test column', meta={'c': 8, 'd': 12})
        c2 = Column(name='a', dtype=int, units='mJy', format='%i',
                    description='test column', meta={'c': 8, 'd': 12})
        assert c1.attrs_equal(c2)

    def test_7(self, Column):
        c1 = Column(name='a', dtype=int, units='mJy', format='%i',
                    description='test column', meta={'c': 8, 'd': 12})
        c2 = Column(name='b', dtype=int, units='mJy', format='%i',
                    description='test column', meta={'c': 8, 'd': 12})
        assert not c1.attrs_equal(c2)

    def test_8(self, Column):
        c1 = Column(name='a', dtype=int, units='mJy', format='%i',
                    description='test column', meta={'c': 8, 'd': 12})
        c2 = Column(name='a', dtype=float, units='mJy', format='%i',
                    description='test column', meta={'c': 8, 'd': 12})
        assert not c1.attrs_equal(c2)

    def test_9(self, Column):
        c1 = Column(name='a', dtype=int, units='mJy', format='%i',
                    description='test column', meta={'c': 8, 'd': 12})
        c2 = Column(name='a', dtype=int, units='erg.cm-2.s-1.Hz-1', format='%i',
                    description='test column', meta={'c': 8, 'd': 12})
        assert not c1.attrs_equal(c2)

    def test_10(self, Column):
        c1 = Column(name='a', dtype=int, units='mJy', format='%i',
                    description='test column', meta={'c': 8, 'd': 12})
        c2 = Column(name='a', dtype=int, units='mJy', format='%g',
                    description='test column', meta={'c': 8, 'd': 12})
        assert not c1.attrs_equal(c2)

    def test_11(self, Column):
        c1 = Column(name='a', dtype=int, units='mJy', format='%i',
                    description='test column', meta={'c': 8, 'd': 12})
        c2 = Column(name='a', dtype=int, units='mJy', format='%i',
                    description='another test column', meta={'c': 8, 'd': 12})
        assert not c1.attrs_equal(c2)

    def test_12(self, Column):
        c1 = Column(name='a', dtype=int, units='mJy', format='%i',
                    description='test column', meta={'c': 8, 'd': 12})
        c2 = Column(name='a', dtype=int, units='mJy', format='%i',
                    description='test column', meta={'e': 8, 'd': 12})
        assert not c1.attrs_equal(c2)

    def test_13(self, Column):
        c1 = Column(name='a', dtype=int, units='mJy', format='%i',
                    description='test column', meta={'c': 8, 'd': 12})
        c2 = Column(name='a', dtype=int, units='mJy', format='%i',
                    description='test column', meta={'c': 9, 'd': 12})
        assert not c1.attrs_equal(c2)

    @pytest.mark.xfail('numpy_lt_1p5')
    def test_col_and_masked_col(self):
        c1 = table.Column(name='a', dtype=int, units='mJy', format='%i',
                          description='test column', meta={'c': 8, 'd': 12})
        c2 = table.MaskedColumn(name='a', dtype=int, units='mJy', format='%i',
                                description='test column', meta={'c': 8, 'd': 12})
        assert c1.attrs_equal(c2)
        assert c2.attrs_equal(c1)
