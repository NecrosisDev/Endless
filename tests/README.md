# Checks

Offline only. They need the exanimate format library (`EXANIMATE_TOOLS` = the folder holding the
`exanimate` package) and a Lua 5.4 `lua.exe` (the script runtime's vendored build).

```powershell
$env:EXANIMATE_TOOLS = '<path to the exanimate format library>'
python -X utf8 -B generator\make_companions.py --export      # out\charroles-endless.rdb, out\companions\
python -X utf8 -B generator\make_template.py                 # out\endless-template.rfc/.ini
Copy-Item out\charroles-endless.rdb assets\charroles.rdb; Copy-Item out\endless-template.rfc,out\endless-template.ini assets\
Copy-Item out\companions\DIALOGUE.md,out\companions\roles.ini companions\
python -X utf8 -B tests\write_goldens.py                     # out\golden-lua (36 areas from the Python reference)
lua.exe tests\test_gen.lua assets\endless-template.rfc assets\endless-template.ini out\golden-lua scripts\gen.lua
lua.exe tests\test_main.lua . assets\endless-template.rfc assets\endless-template.ini
python -X utf8 -B tests\batch_check.py 5                     # 50 areas: grid rules, reachability, determinism
python -X utf8 -B tools\make_dist.py                          # dist\mods\com.necrosis.endless\ for the installer
```

`out/` is not committed; the four files under `assets/` built from the game's own data are not either.
