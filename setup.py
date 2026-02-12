from setuptools import setup, Extension
import pybind11

# MSVC flags
cpp_args = ['/O2', '/std:c++17', '/openmp']

ext_modules = [
    Extension(
        "cpp_engine",
        ["cpp_extension/bindings.cpp", "cpp_extension/knn.cpp", "cpp_extension/backtester.cpp", "cpp_extension/indicators.cpp", "cpp_extension/optimizer.cpp"],
        include_dirs=[pybind11.get_include()],
        language='c++',
        extra_compile_args=['/std:c++17', '/O2', '/openmp']
    ),
]

setup(
    name='cpp_engine',
    version='0.1.0',
    description='C++ Optimized Engine for Trading Bot',
    ext_modules=ext_modules,
)
