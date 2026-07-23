# FindQuantLib.cmake — Locate QuantLib headers and library
#
# Sets:
#   QuantLib_FOUND        — TRUE if found
#   QuantLib_INCLUDE_DIRS — include path
#   QuantLib_LIBRARIES    — libraries to link
#   QuantLib::QuantLib    — imported target

include(FindPackageHandleStandardArgs)

find_path(QuantLib_INCLUDE_DIR
    NAMES ql/quantlib.hpp
    HINTS
        ENV QuantLib_DIR
        /usr/local/include
        /usr/include
    PATH_SUFFIXES include
)

find_library(QuantLib_LIBRARY
    NAMES QuantLib ql
    HINTS
        ENV QuantLib_DIR
        /usr/local/lib
        /usr/lib
    PATH_SUFFIXES lib lib64
)

find_package_handle_standard_args(QuantLib
    REQUIRED_VARS QuantLib_LIBRARY QuantLib_INCLUDE_DIR
)

if(QuantLib_FOUND)
    set(QuantLib_INCLUDE_DIRS ${QuantLib_INCLUDE_DIR})
    set(QuantLib_LIBRARIES    ${QuantLib_LIBRARY})

    if(NOT TARGET QuantLib::QuantLib)
        add_library(QuantLib::QuantLib UNKNOWN IMPORTED)
        set_target_properties(QuantLib::QuantLib PROPERTIES
            IMPORTED_LOCATION             "${QuantLib_LIBRARY}"
            INTERFACE_INCLUDE_DIRECTORIES "${QuantLib_INCLUDE_DIR}"
        )
    endif()
endif()

mark_as_advanced(QuantLib_INCLUDE_DIR QuantLib_LIBRARY)
