"""SAP Colombia — Módulo de facturación electrónica, contabilidad y cumplimiento DIAN."""
import sys
from sap_colombia import dbutil

sys.modules.setdefault("dbutil", dbutil)
