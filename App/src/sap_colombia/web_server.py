"""Alias del módulo web_server dentro del paquete sap_colombia."""
import importlib
import sys

_mod = importlib.import_module("web_server")
sys.modules[__name__] = _mod
