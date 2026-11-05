from setuptools import find_packages, setup

from trivia_sync import __version__

setup(
	name="trivia_sync",
	version=__version__,
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=[
		"requests>=2.31.0"
	]
)
