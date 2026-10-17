#!/usr/bin/env python3
"""
Alias de compatibilidad hacia gestor_sistema.py.
El script principal ha sido renombrado a gestor_sistema.py para reflejar
sus capacidades completas de configuración, clonación de BD, respaldos y arranque.
"""
import os
import sys
import runpy

if __name__ == "__main__":
    target = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gestor_sistema.py")
    sys.argv[0] = target
    runpy.run_path(target, run_name="__main__")
