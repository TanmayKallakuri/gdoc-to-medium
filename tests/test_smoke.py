import gdoc_to_medium


def test_package_version_importable():
    assert isinstance(gdoc_to_medium.__version__, str)
    assert gdoc_to_medium.__version__
