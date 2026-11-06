# native/Makefile — build core native + uji.
#
# Semua modul di-port dari Python; Python dipakai HANYA untuk menghasilkan
# golden.bin (acuan byte) di tahap uji, tidak ikut ke binary.

CXX      ?= g++
CXXFLAGS ?= -O2 -std=c++17 -Wall -Wextra -Wno-address-of-packed-member
PKGS     := gtk+-3.0 json-glib-1.0 lua5.4 libcurl openssl
PKG_CFLAGS := $(shell pkg-config --cflags $(PKGS))
PKG_LIBS   := $(shell pkg-config --libs $(PKGS))

BUILD := build
CORE  := $(BUILD)/liblucifer.a
SRC   := protocol.cpp world.cpp items.cpp
OBJ   := $(SRC:%.cpp=$(BUILD)/%.o)

TESTS    := $(BUILD)/test_protocol $(BUILD)/test_world $(BUILD)/test_items
TEST_BIN := $(TESTS)

.PHONY: all test golden clean run

all: $(CORE)

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/%.o: %.cpp protocol.h | $(BUILD)
	$(CXX) $(CXXFLAGS) $(PKG_CFLAGS) -c $< -o $@

$(CORE): $(OBJ)
	ar rcs $@ $^

$(BUILD)/test_protocol: tests/test_protocol.cpp $(CORE) protocol.h | $(BUILD)
	$(CXX) $(CXXFLAGS) $(PKG_CFLAGS) $< $(CORE) -o $@ $(PKG_LIBS)

$(BUILD)/test_world: tests/test_world.cpp $(CORE) world.h | $(BUILD)
	$(CXX) $(CXXFLAGS) $(PKG_CFLAGS) $< $(CORE) -o $@ $(PKG_LIBS)

$(BUILD)/test_items: tests/test_items.cpp $(CORE) items.h | $(BUILD)
	$(CXX) $(CXXFLAGS) $(PKG_CFLAGS) $< $(CORE) -o $@ $(PKG_LIBS)

# golden dihasilkan dari Python: acuan byte untuk uji kesetaraan.
golden:
	../.venv/bin/python tests/gen_golden.py
	../.venv/bin/python tests/gen_world_golden.py
	../.venv/bin/python tests/gen_items_golden.py

# Uji dijalankan dari ROOT repo (butuh data/items.dat), bukan dari native/.
test: $(TEST_BIN) golden
	@cd .. && status=0; \
	for t in $(addprefix native/,$(TEST_BIN)); do \
	  echo; ./$$t || status=1; \
	done; exit $$status

run: test

clean:
	rm -rf $(BUILD)
