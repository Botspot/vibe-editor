# VIBE-EDITOR
100% vibe-coded CSV/TSV spreadsheet editor with strong hacker vibes

<img width="959" height="699" alt="image" src="https://github.com/user-attachments/assets/c683d15d-a74a-4848-a2c7-47a7e1b69bd3" />

A few days ago I wanted a simple CSV/TSV file editor which:
- Is actually fun to use, to help me want to do my taxes 🤣
- Is minimal and fast on Raspberry Pi hardware
- Has a cool hacker-style dark mode
- Has intuitive keyboard/mouse navigation, that actually makes sense to me
- Supports cells with drop-down menus and checkboxes
- Colors negative numbers red.
- Displays a sum when multiple numeric cells are selected
- Can search the spreadsheet easily

For years I've just been suffering with the choice between LibreOffice, and a poorly written shell script I made, but _this is 2026!_ Learning to code is now 100% optional for things like this.
After about an hour, this is what Gemini 3.1 Pro delivered. Don't ask me how it works. I don't know how it works. I don't need to.

## Purpose
This repo serves as a time capsule for what AI was capable of during this point in time. A year ago making something like this would have been a struggle. Now it was easy. How much will it improve in another year?  
This is mainly as a demo and for my personal use. However, if you use this, like it, and want to see a feature added, go [open an issue](https://github.com/Botspot/vibe-editor/issues) or [pull request](https://github.com/Botspot/vibe-editor/pulls).

## Features

- To support cell formatting in raw text, I made a simple flag system.
  - A column title ending with `:ro` means **read-only**, so you can't make accidental changes.
  - A column title ending with `:chk` means **checkbox**, where TRUE means checked and anything else means unchecked.
  - A column title ending with `:cb=value1,value2,value3` means **combo-box**, where "value1", "value2", and "value3" are easy to choose from a drop-down menu.
- Fully custom keyboard navigation. It might not come naturally to you, but to me it makes much more sense than normal spreadsheet editors.
  - Navigate cells using the arrow keys.
  - Press Enter to start editing that cell.
    - While editing, all 4 arrow keys work inside the text box. Up arrow skips to the beginning of the line, Down skips to the end.
    - Press Enter again to exit editing. The selection is *not* shifted downward. I prefer it this way.
  - Press Ctrl+S to save
  - Press Ctrl+F and start typing a phrase to search for
    - The search starts from the visible part of the spreadsheet and searches down, and wraps around if no matches found.
    - Press Enter to highlight the next result **below** the current one.
    - Press Shift+Enter to highlight the next result **above** the current one.
- Select multiple numeric cells at once, and the status bar will display their sum.
- Each column will auto-scale to the width of the widest value in your data.
  - If your spreadsheet is wider than the app window, horizontal scrolling is smooth and does not snap to the nearest column. (like LibreOffice does 😠)
- Open a file by specifying it as an argument to this python script.
  - When saving, it makes changes to the input file you specified.
- The usual annoying stuff is gone. (Looking at you, LibreOffice...)
  - No 30-second app launch time.
  - No "helpful tips" popup.
  - No "confirm file overwrite" popup.
  - No "close with unsaved changes" popup.
  - No "CSV format is dumb and you should consider using ODS" popup.

# Dependencies
This uses PyQT5, so on Debian-based operating systems this should be enough:
```
sudo apt install python3-pyqt5 qtwayland5
```

# DEMO
I've included a fictitious TSV file to show the features.  
To run the demo:
```
git clone https://github.com/Botspot/vibe-editor
cd vibe-editor
./vibe-editor.py ./demo.tsv
```


