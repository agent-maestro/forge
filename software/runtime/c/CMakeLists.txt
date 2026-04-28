cmake_minimum_required(VERSION 3.16)
project(libmonogate
    VERSION 0.0.1
    DESCRIPTION "C runtime for EML-lang"
    LANGUAGES C
)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)

add_library(monogate STATIC libmonogate.c)
target_include_directories(monogate PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
    $<INSTALL_INTERFACE:include>
)
target_link_libraries(monogate PUBLIC m)

# Install headers + library + pkg-config file
install(FILES libmonogate.h DESTINATION include)
install(TARGETS monogate ARCHIVE DESTINATION lib)
install(FILES pkg-config/monogate.pc DESTINATION lib/pkgconfig)

# Tests
enable_testing()
add_subdirectory(tests)
