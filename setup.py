"""
Setup.py for superset-patchup
"""
from setuptools import setup, find_packages

setup(
    name='hq_superset',
    version='0.1.0',
    description='CommCareHQ Superset Integration',
    license='Apache2',
    author='Dimagi Inc',
    author_email='sreddy@dimagi.com',
    url='https://github.com/dimagi/hq_superset',
    packages=find_packages(exclude=['docs', 'tests']),
    include_package_data=True,
    install_requires=[
        'dimagi-superset==1.4.1',
        'authlib',
    ],
    classifiers=[
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7'
        'Programming Language :: Python :: 3.8'
    ],
)
