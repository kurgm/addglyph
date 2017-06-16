# -*- coding: utf-8 -*-

from distutils.core import setup

import py2exe

setup(
	options={
		"py2exe": {
			"compressed": 0,
			"optimize": 2,
			"bundle_files": 1
		}
	},
	console=[{"script": "addglyph.py"}],
	zipfile=None,
	data_files=["readme.txt"],
	name="Add Glyphs",
	version="1.2",
	description="Adds blank glyphs to a font file",
	author="Kurogoma"
)
