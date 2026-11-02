cmake_minimum_required(VERSION 3.16)
project(lucifer-desktop CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(PkgConfig REQUIRED)
pkg_check_modules(GTK REQUIRED gtk+-3.0)
pkg_check_modules(JSONGLIB REQUIRED json-glib-1.0)

add_executable(lucifer-desktop src/ui.cpp src/data.cpp src/http.cpp)
target_include_directories(lucifer-desktop PRIVATE
    ${GTK_INCLUDE_DIRS} ${JSONGLIB_INCLUDE_DIRS} src)
target_link_libraries(lucifer-desktop PRIVATE
    ${GTK_LIBRARIES} ${JSONGLIB_LIBRARIES})
target_compile_options(lucifer-desktop PRIVATE ${GTK_CFLAGS_OTHER} -Wall -Wextra)

install(TARGETS lucifer-desktop RUNTIME DESTINATION bin)
