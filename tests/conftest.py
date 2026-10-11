import os

# Las pruebas de interfaz se ejecutan sin abrir ventanas reales.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")