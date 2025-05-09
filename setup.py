from setuptools import setup, find_packages

setup(
    name='pkgtst',
    version='0.2.0',
    packages=find_packages(),
    package_dir={
        'pkgtst': 'pkgtst'
    },
    entry_points={
        'console_scripts': [
            'pkgtst=pkgtst.tools.pkgtst:main'
        ],
    },
    options={
        'egg_info': {
            'egg_base': '.'
        }
    },
    install_requires=[
        'PyYAML==6.0.1',
        'Jinja2==3.0.3'
    ],
    include_package_data=True,
    zip_safe=False
)
