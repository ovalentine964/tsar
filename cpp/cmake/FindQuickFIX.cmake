# FindQuickFIX.cmake — Locate QuickFIX headers and library
#
# Sets:
#   QuickFIX_FOUND        — TRUE if found
#   QuickFIX_INCLUDE_DIRS — include path
#   QuickFIX_LIBRARIES    — libraries to link
#   QuickFIX::QuickFIX    — imported target

include(FindPackageHandleStandardArgs)

find_path(QuickFIX_INCLUDE_DIR
    NAMES quickfix/Application.h
    HINTS
        ENV QuickFIX_DIR
        /usr/local/include
        /usr/include
    PATH_SUFFIXES include
)

find_library(QuickFIX_LIBRARY
    NAMES quickfix
    HINTS
        ENV QuickFIX_DIR
        /usr/local/lib
        /usr/lib
    PATH_SUFFIXES lib lib64
)

find_package_handle_standard_args(QuickFIX
    REQUIRED_VARS QuickFIX_LIBRARY QuickFIX_INCLUDE_DIR
)

if(QuickFIX_FOUND)
    set(QuickFIX_INCLUDE_DIRS ${QuickFIX_INCLUDE_DIR})
    set(QuickFIX_LIBRARIES    ${QuickFIX_LIBRARY})

    if(NOT TARGET QuickFIX::QuickFIX)
        add_library(QuickFIX::QuickFIX UNKNOWN IMPORTED)
        set_target_properties(QuickFIX::QuickFIX PROPERTIES
            IMPORTED_LOCATION             "${QuickFIX_LIBRARY}"
            INTERFACE_INCLUDE_DIRECTORIES "${QuickFIX_INCLUDE_DIR}"
        )
    endif()
endif()

mark_as_advanced(QuickFIX_INCLUDE_DIR QuickFIX_LIBRARY)
