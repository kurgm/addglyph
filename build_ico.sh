#!/usr/bin/env bash

declare -a sizes=(16 32 48 256)
declare -a pngs=()
for size in ${sizes[@]}; do
  inkscape -z -e $PWD/icon-$size.png -w $size -h $size $PWD/icon.svg
  pngs+=(icon-$size.png)
done
convert ${pngs[@]} icon.ico
rm ${pngs[@]}
