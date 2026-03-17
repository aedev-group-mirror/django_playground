# THIS FILE IS EXCLUSIVELY MAINTAINED by the project aedev.project_tpls v0.3.77
""" setup of django_playground playground: django_playground playground main module. """
import sys
# noinspection PyUnresolvedReferences
import pathlib
# noinspection PyUnresolvedReferences
import setuptools


print("SetUp " + __name__ + ": " + sys.executable + str(sys.argv) + f" {sys.path=}")

setup_kwargs = {
    'author': 'AndiEcker',
    'author_email': 'aecker2@gmail.com',
    'classifiers': [
        'Development Status :: 3 - Alpha',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.12',
        'Topic :: Software Development',
        'Typing :: Typed',
    ],
    'description': 'django_playground playground: django_playground playground main module',
    'extras_require': {
        'dev': [
            'aedev_project_tpls',
            'sphinx',
            'sphinx-rtd-theme',
            'sphinx_autodoc_typehints',
            'sphinx_paramlinks',
            'aedev_project_vars',
            'anybadge',
            'flake8',
            'mypy',
            'pylint',
            'pytest',
            'pytest-cov',
            'typing',
            'types-setuptools',
        ],
        'docs': [
            'sphinx',
            'sphinx-rtd-theme',
            'sphinx_autodoc_typehints',
            'sphinx_paramlinks',
            'aedev_project_vars',
        ],
        'tests': [
            'anybadge',
            'flake8',
            'mypy',
            'pylint',
            'pytest',
            'pytest-cov',
            'typing',
            'types-setuptools',
        ],
    },
    'install_requires': [],
    'keywords': [
        'configuration',
        'development',
        'environment',
        'productivity',
    ],
    'license': 'GPL-3.0-or-later',
    'long_description': (pathlib.Path(__file__).parent / 'README.md').read_text(encoding='utf-8'),
    'long_description_content_type': 'text/markdown',
    'name': 'django_playground',
    'package_data': {
        '': [
            'docs/Makefile',
            'docs/features_and_examples.rst',
            'docs/requirements.txt',
            'docs/conf.py',
            'docs/index.rst',
        ],
    },
    'packages': [],
    'project_urls': {
        'Bug Tracker': 'https://gitlab.com/aedev-group/django_playground/-/issues',
        'Documentation': 'https://django_playground.readthedocs.io/en/latest/_autosummary/django_playground.html',
        'Repository': 'https://gitlab.com/aedev-group/django_playground',
        'Source': 'https://django_playground.readthedocs.io/en/latest/_modules/django_playground.html',
    },
    'python_requires': '>=3.12',
    'url': 'https://gitlab.com/aedev-group/django_playground',
    'version': '0.3.7',
    'zip_safe': False,
}

if __name__ == "__main__":
    setuptools.setup(**setup_kwargs)
    pass
