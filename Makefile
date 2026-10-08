# Lucifer Linux — Makefile
# Build library ENet patch Growtopia + siapkan lingkungan Python.

SHELL      := /bin/bash
VENV       := .venv
PY         := $(VENV)/bin/python
PIP        := $(VENV)/bin/pip
LUCIFER    := $(VENV)/bin/lucifer
UNAME_S    := $(shell uname -s)

ifeq ($(UNAME_S),Linux)
    LIB_EXT   = .so
    CXXFLAGS  = -fPIC -O2
    DEFINES   = -DENET_IMPLEMENTATION
else ifeq ($(UNAME_S),Darwin)
    LIB_EXT   = .dylib
    CXXFLAGS  = -fPIC -O2
    DEFINES   = -DENET_IMPLEMENTATION
else
    LIB_EXT   = .dll
    CXXFLAGS  =
    DEFINES   = -DENET_DLL -DENET_IMPLEMENTATION
endif

CXX     ?= $(shell command -v g++ >/dev/null && echo g++ || echo clang++)
ENET_LIB = enet/enet$(LIB_EXT)

.PHONY: all enet venv install doctor probe test test-offline run web clean distclean help

all: venv enet install
	@echo
	@echo "  ✅ Selesai. Coba:  make doctor && make probe"
	@echo

# ------------------------------------------------------------------ #
# 1. ENet (single-header, patch Growtopia)
# ------------------------------------------------------------------ #
enet: $(ENET_LIB)

$(ENET_LIB): enet/enet.cpp enet/enet.h
	@echo "==> Kompilasi ENet patch Growtopia ($(UNAME_S))"
	$(CXX) $(CXXFLAGS) enet/enet.cpp -shared $(DEFINES) -o $@
	@nm -D --defined-only $@ 2>/dev/null | grep -q enet_host_use_new_packet \
		&& echo "    ✓ simbol Growtopia (use_new_packet/crc32/range_coder) ada" \
		|| (echo "    ✗ simbol Growtopia TIDAK ADA"; exit 1)
	@ls -la $@

# ------------------------------------------------------------------ #
# 2. Python
# ------------------------------------------------------------------ #
$(VENV)/bin/activate:
	@echo "==> Membuat virtualenv"
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip -q

venv: $(VENV)/bin/activate

install: venv
	@echo "==> Memasang dependensi Python"
	$(PIP) install -q -r requirements.txt
	@echo "    ✓ dependensi terpasang"

# ------------------------------------------------------------------ #
# 3. Pemeriksaan
# ------------------------------------------------------------------ #
doctor: install enet
	@$(LUCIFER) doctor

probe: install enet
	@$(LUCIFER) probe

items: install
	@$(LUCIFER) items data/items.dat

# ------------------------------------------------------------------ #
# 4. Menjalankan
# ------------------------------------------------------------------ #
run: install enet
	@$(LUCIFER) run

web: install enet
	@$(LUCIFER) web --host 0.0.0.0 --port 8787

test: install enet
	@echo "$(BOLD)== Uji unit (tanpa jaringan) ==$(RESET)"
	@$(PY) tests/test_unit.py
	@echo ""
	@echo "$(BOLD)== Uji modul ltoken ==$(RESET)"
	@$(PY) tests/test_ltoken.py
	@echo ""
	@echo "$(BOLD)== Uji UI tab 'Dari HP' ==$(RESET)"
	@$(PY) tests/test_ui_hp.py
	@echo ""
	@echo "$(BOLD)== Uji dashboard web ==$(RESET)"
	@$(PY) tests/test_web.py
	@echo ""
	@echo "$(BOLD)== Uji login dari dashboard ==$(RESET)"
	@$(PY) tests/test_login_ui.py
	@echo ""
	@echo "$(BOLD)== Uji integrasi nyata (butuh internet + server Growtopia) ==$(RESET)"
	@$(PY) tests/test_integration.py || \
	  echo "$(YELLOW)  (uji integrasi dilewati/gagal — cek koneksi internet)$(RESET)"

test-offline: install enet
	@$(PY) tests/test_unit.py && $(PY) tests/test_ltoken.py && $(PY) tests/test_ui_hp.py && $(PY) tests/test_web.py && $(PY) tests/test_login_ui.py

# ------------------------------------------------------------------ #
# 5. Bersih-bersih
# ------------------------------------------------------------------ #
clean:
	rm -f enet/enet$(LIB_EXT)
	find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

distclean: clean
	rm -rf $(VENV) .pytest_cache data/items.dat data/world.dat

help:
	@echo "Lucifer Linux — perintah make:"
	@echo "  make            build ENet + siapkan venv + dependensi"
	@echo "  make doctor     cek lingkungan"
	@echo "  make probe      uji handshake ke server Growtopia asli"
	@echo "  make items      periksa items.dat"
	@echo "  make run        jalankan bot + skrip"
	@echo "  make web        jalankan dashboard (port 8787)"
	@echo "  make test       jalankan pengujian"
	@echo "  make clean      hapus hasil build"
