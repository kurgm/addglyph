#!/usr/bin/env python
# -*- coding: utf-8 -*-
import codecs
import logging
import os
import re
import sys
import tempfile

from fontTools.ttLib import TTFont, reorderFontTables
from fontTools.ttLib.tables import _c_m_a_p, _g_l_y_f


hexEntityRe = re.compile(r"&#x([\da-fA-F]{1,8});")
decEntityRe = re.compile(r"&#(\d+);")


def myunichr(cp):
	assert 0 <= cp <= 0x10FFFF, "invalid codepoint"
	return r"\U{:08x}".format(cp).decode("unicode-escape")


def decodeEntity(s):
	return hexEntityRe.sub(lambda m: r"\U{:0>8s}".format(m.group(1)).decode("unicode-escape"), decEntityRe.sub(lambda m: myunichr(int(m.group(1), 10)), s))


def myord(c):
	buf = []
	i = 0
	l = len(c)
	while i < l:
		oc0 = ord(c[i])
		i += 1
		if i < l and 0xD800 <= oc0 < 0xDC00:
			oc1 = ord(c[i])
			i += 1
			buf.append(0x10000 + ((oc0 & 0x3FF) << 10) | (oc1 & 0x3FF))
		else:
			buf.append(oc0)
	return buf


def pause():
	if os.name == "nt":
		os.system("pause")
	else:
		raw_input("Press Enter to continue . . .")


def addglyph(fontfile, textfiles):
	chars = set()

	for f in textfiles:
		try:
			with codecs.open(f, encoding="utf-8-sig") as infile:
				dat = infile.read()
		except:
			logging.error("Error while loading text file")
			raise
		cps = myord(decodeEntity(dat))
		chars.update(cps)

	chars -= {0x9, 0xa, 0xd}  # exclude \t \r \n

	try:
		ttf = TTFont(fontfile)
	except:
		logging.error("Error while loading font file")
		raise

	cmap = ttf["cmap"]
	sub4 = cmap.getcmap(platformID=3, platEncID=1)
	subt = cmap.getcmap(platformID=3, platEncID=10)
	if subt is None:
		assert sub4 is not None, "cmap subtable (format=4) not found"
		subt = _c_m_a_p.cmap_format_12(12)
		subt.platformID = 3
		subt.platEncID = 10
		subt.format = 12
		subt.reserved = 0
		subt.length = 0   # will be recalculated by compiler
		subt.language = 0
		subt.nGroups = 0  # will be recalculated by compiler
		if not hasattr(subt, "cmap"):
			subt.cmap = {}
		subt.cmap.update(sub4.cmap)
		cmap.tables.append(subt)
		logging.info("cmap subtable (format=12) created")

	smap = subt.cmap

	hmtx = ttf["hmtx"]
	vmtx = ttf["vmtx"]
	glyf = ttf["glyf"]

	addedTotal = 0
	for c in chars:
		if c not in smap:
			if c < 0x10000:
				glyphname = "uni%04X" % c
				if sub4 is not None:
					sub4.cmap.setdefault(c, glyphname)
			else:
				glyphname = "u%04X" % c
			smap[c] = glyphname
			hmtx[glyphname] = vmtx[glyphname] = (1024, 0)
			glyph = _g_l_y_f.Glyph()
			glyph.xMin = glyph.yMin = glyph.xMax = glyph.yMax = 0
			glyf[glyphname] = glyph
			logging.info("added: U+%04X" % c)
			addedTotal += 1
		else:
			logging.info("already in font: U+%04X" % c)

	logging.info("%d glyphs added!" % addedTotal)
	logging.info("saving...")

	outfont = fontfile[:-4] + "_new" + fontfile[-4:]
	try:
		with tempfile.TemporaryFile(prefix="add-glyphs") as tmp:
			ttf.save(tmp, reorderTables=False)

			# Bring `glyf` table to the last so that the font can be edited with TTEdit
			logging.info("reordering...")
			tmp.flush()
			tmp.seek(0)
			with open(outfont, "wb") as outfile:
				reorderFontTables(tmp, outfile, tableOrder=["head", "hhea", "maxp", "post", "OS/2", "name", "gasp", "cvt ", "fpgm", "prep", "cmap", "loca", "hmtx", "mort", "GSUB", "vhea", "vmtx", "glyf"])
	except:
		logging.error("Error while saving font file")
		raise

	logging.info("saved successfully: %s" % outfont)


def main():
	files = sys.argv[1:]
	fontfile = None
	textfiles = []

	for f in files:
		if f[-4:].lower() in (".ttf", ".otf"):
			assert fontfile is None, "multiple font files specified"
			fontfile = f
		else:
			textfiles.append(f)

	assert fontfile is not None, "no font file specified"
	assert textfiles, "no text files specified"

	logging.info("font file = %s" % fontfile)
	logging.info("text file(s) = %s" % ", ".join(textfiles))

	addglyph(fontfile, textfiles)


if __name__ == "__main__":
	logging.basicConfig(level=logging.DEBUG)
	try:
		main()
	except:
		logging.exception("An error occurred")
		pause()
		sys.exit(1)
	pause()
