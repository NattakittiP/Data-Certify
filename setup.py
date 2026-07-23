"""
Setup configuration for the data_certify package.

Theoretical-framework companion implementation -- prepared for submission
to Earth Science Informatics.
"""

from setuptools import setup, find_packages

setup(
    name             = "data_certify",
    version          = "0.1.4",
    description      = (
        "DATA-CERTIFY: A Dataset Trustworthiness Audit Framework for "
        "Disaster Seismic Data. Theoretical-framework companion implementation."
    ),
    author           = "Nattakitti Piyavechvirat",
    python_requires  = ">=3.8",
    packages         = find_packages(),
    install_requires = [
        "numpy>=1.21.0",
    ],
    extras_require   = {
        # scipy: only for tests/test_scientific_validity.py's scipy cross-checks
        # (core package stays numpy-only) -- kept in sync with pyproject.toml.
        "test": ["pytest>=7.0", "scipy>=1.7"],
        "prepare": ["pandas>=1.3"],
        "all": ["pytest>=7.0", "pandas>=1.3", "scipy>=1.7"],
    },
    classifiers      = [
        "Programming Language :: Python :: 3",
        "License :: All Rights Reserved",
        "Operating System :: OS Independent",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
)
