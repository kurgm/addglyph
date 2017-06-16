●せつめいしょ

簡単にいうとフォントに空のグリフを追加するプログラム


■つかいかた

フォントファイル(.otfまたは.ttfを1つだけ)とテキストファイル(複数可)を同時に選択して
「addglyph.exe」にドラッグ・アンド・ドロップする

↓

テキストファイルに入ってる文字で、フォントファイルにグリフがないものを
追加したフォントが新規作成される！

↓

やったぜ。


■ちゅうい

・テキストファイルはUTF-8で作成してください

・フォントファイル以外がテキストファイルとみなされます
　（ので拡張子は.txtじゃなくてもいいです）
　（が、中身がテキストファイルじゃないと（.docとか入れても）ムリです）

・できたフォントは、元のフォントの拡張子の前に _new を付けたものになります
　（すでに存在する場合は勝手に上書きされます。注意）
　（元のフォントは変更されません）
　例： 851tegaki_zatsu.ttf -> 851tegaki_zatsu_new.ttf


■ひんと

テキストファイル内の「&#x1F600;」や「&#128512;」は、U+1F600の文字として処理されます
（16進数の1F600は、10進数の128512）
（もちろんU+1F600に限りません）


■ひょうじ

実行するとコンソールにいろいろ表示されます

「INFO:root:font file = なんとか.ttf」…処理対象のフォントファイル
「INFO:root:text file(s) = かん.txt, とか.txt」…処理対象のテキストファイル
「INFO:root:cmap subtable (format=12) created」…U+10000以上を追加するための処理をした
「～～UserWarning: 'created' timestamp seems very low～～～」…たぶん無視してok
「INFO:root:added: U+xxxx」…U+xxxxをフォントに追加した
「INFO:root:already in font: U+xxxx」…U+xxxxは既にフォントに入っている
「INFO:root:### glyphs added!」…###個のグリフを追加した
「INFO:root:saving...」…保存中
「INFO:root:reordering...」…フォントファイル内のテーブルを並び替え中
「INFO:root:saved successfully: なんとか_new.ttf」…保存先フォント
「続行するには何かキーを押してください . . .」…何かキーを押すと終了します

以下はエラー時に表示されます

「AssertionError: multiple font files specified」…複数のフォントファイルが指定されています
（.otf, .ttf は1つだけ指定してください）
「ERROR:root:Error while loading text file」…テキストファイルの読み込みに失敗しました
（存在するテキストファイルを指定しているか確認してください）
「ERROR:root:Error while loading font file」…フォントファイルの読み込みに失敗しました
（存在する壊れていないフォントファイルを指定しているか確認してください）
「ERROR:root:Error while saving font file」…フォントファイルの書き込みに失敗しました
（書き込みの権限があるか、ディスクに空き容量があるか、ファイルが使用中でないか確認して下さい）

※一瞬で消えて表示が見えない時はコマンド プロンプトなどから実行してください
　そして @kurgm まで報告していただけると助かります
　そのほかの表示があって失敗する場合も @kurgm まで報告していただけると助かります


■なにかあったら

@kurgm まで


2016-08-22    version 1.2
