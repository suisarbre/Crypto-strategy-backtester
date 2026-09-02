import os

from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext

import pybind11

# OpenMP is required for the optimizer's parallel loops. Set
# CPP_ENGINE_NO_OPENMP=1 to build without it (single-threaded but correct) on
# toolchains where OpenMP is unavailable, e.g. Apple clang without libomp.
NO_OPENMP = os.environ.get("CPP_ENGINE_NO_OPENMP", "") not in ("", "0")


class BuildExt(build_ext):
    """Pick compiler flags at build time: MSVC vs GCC/Clang."""

    def build_extensions(self):
        if self.compiler.compiler_type == "msvc":
            compile_args = ["/O2", "/std:c++17", "/EHsc"]
            link_args = []
            if not NO_OPENMP:
                compile_args.append("/openmp")
        else:
            compile_args = ["-O3", "-std=c++17"]
            link_args = []
            if not NO_OPENMP:
                compile_args.append("-fopenmp")
                link_args.append("-fopenmp")
        for ext in self.extensions:
            ext.extra_compile_args = compile_args
            ext.extra_link_args = link_args
        super().build_extensions()


ext_modules = [
    Extension(
        "cpp_engine",
        [
            "cpp_extension/knn.cpp",
            "cpp_extension/optimizer.cpp",
            "cpp_extension/signal_evaluator.cpp",
            "cpp_extension/bindings.cpp",
            "cpp_extension/backtester.cpp",
            "cpp_extension/indicators.cpp",
            "cpp_extension/factory.cpp",
        ],
        include_dirs=[pybind11.get_include(), "cpp_extension"],
        language="c++",
    ),
]

setup(
    name="cpp_engine",
    version="0.1.0",
    description="C++ Optimized Engine for Trading Bot",
    ext_modules=ext_modules,
    cmdclass={"build_ext": BuildExt},
)
