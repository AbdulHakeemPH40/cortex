python src/main.py


Remove-Item -Recurse -Force build, dist
.\venv\Scripts\python.exe -m PyInstaller cortex.spec
.\build_installer.

.\build.ps1



cd dist\Cortex
.\Cortex.exe