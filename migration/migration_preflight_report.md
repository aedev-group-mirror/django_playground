# Django / CMS Migration Pre-flight Report

**Python**: 3.9.21
**Python OK**: partial
**Database**: /home/andi/src/kairos/project.db (8.51 MB)
**Media files**: 532 files

## Deprecated API Findings

### `[Step 3] pytz`
- `setup.py`

## Effort Estimates

- **Step 1 (→ Django 3.2)**: ~1 hours
- **Step 2 (→ Django 4.2)**: ~2 hours
- **Step 3 (→ Django 5.2)**: ~2 hours
- **Step 4 (→ CMS 4)**: ~4-8 hours (major architectural change)
- **Step 5 (→ CMS 5)**: ~1 hours
- **Total estimate**: ~10-20 hours depending on codebase complexity
- **Bootstrap4 migration (Step 4)**: ~2-4 EXTRA hours – manual Bootstrap4 plugin content migration

## Installed Packages

| Package | Version |
| ------- | ------- |
| ae-django-utils | 0.3.1 |
| ae-parse-date | 0.3.5 |
| ae_base | 0.3.38 |
| ae_console | 0.3.93 |
| ae_core | 0.3.82 |
| ae_dynamicod | 0.3.15 |
| ae_files | 0.3.25 |
| ae_literal | 0.3.35 |
| ae_notify | 0.3.5 |
| ae_paths | 0.3.43 |
| ae_shell | 0.3.12 |
| ae_template | 0.3.2 |
| ae_updater | 0.3.17 |
| aedev_base | 0.3.4 |
| aedev_commands | 0.3.8 |
| aedev_project_vars | 0.3.1 |
| alabaster | 0.7.16 |
| anybadge | 1.16.0 |
| argcomplete | 3.6.3 |
| asgiref | 3.6.0 |
| astroid | 3.3.11 |
| babel | 2.18.0 |
| certifi | 2022.12.7 |
| charset-normalizer | 3.0.1 |
| click | 8.1.8 |
| coverage | 7.10.7 |
| cssselect2 | 0.7.0 |
| dill | 0.4.1 |
| django | 3.1.14 |
| django-classy-tags | 3.0.1 |
| django-cms | 3.8.0 |
| django-crispy-forms | 1.14.0 |
| django-filer | 2.2.4 |
| django-formtools | 2.4 |
| django-js-asset | 2.0.0 |
| django-mptt | 0.14.0 |
| django-polymorphic | 3.1.0 |
| django-sekizai | 3.0.1 |
| django-treebeard | 4.4 |
| djangocms-admin-style | 2.0.2 |
| djangocms-attributes-field | 2.1.0 |
| djangocms-bootstrap4 | 2.0.0 |
| djangocms-file | 3.0.0 |
| djangocms-googlemap | 2.0.0 |
| djangocms-icon | 2.0.0 |
| djangocms-link | 3.1.0 |
| djangocms-picture | 3.0.0 |
| djangocms-style | 3.0.0 |
| djangocms-text-ckeditor | 4.0.0 |
| djangocms-video | 3.0.0 |
| docutils | 0.21.2 |
| easy-thumbnails | 2.8.5 |
| exceptiongroup | 1.3.1 |
| flake8 | 7.3.0 |
| freetype-py | 2.5.1 |
| html5lib | 1.1 |
| idna | 3.4 |
| imagesize | 1.5.0 |
| importlib_metadata | 8.7.1 |
| iniconfig | 2.1.0 |
| isort | 6.1.0 |
| jinja2 | 3.1.6 |
| librt | 0.8.1 |
| lxml | 4.9.2 |
| markupsafe | 3.0.3 |
| mccabe | 0.7.0 |
| mypy | 1.19.1 |
| mypy_extensions | 1.1.0 |
| packaging | 25.0 |
| pathspec | 1.0.4 |
| pillow | 9.4.0 |
| pip | 26.0.1 |
| pipx | 1.8.0 |
| platformdirs | 4.4.0 |
| pluggy | 1.6.0 |
| pycairo | 1.28.0 |
| pycodestyle | 2.14.0 |
| pyflakes | 3.4.0 |
| pygments | 2.19.2 |
| pyjnius | 1.7.0 |
| pylint | 3.3.9 |
| pylint-django | 2.7.0 |
| pylint-plugin-utils | 0.9.0 |
| pytest | 8.4.2 |
| pytest-cov | 7.0.0 |
| pytest-django | 4.11.1 |
| pytz | 2022.7.1 |
| reportlab | 3.6.12 |
| requests | 2.31.0 |
| rlpycairo | 0.4.0 |
| setuptools | 80.9.0 |
| six | 1.16.0 |
| snowballstemmer | 3.0.1 |
| sphinx | 7.4.7 |
| sphinx-autodoc-typehints | 2.3.0 |
| sphinx-paramlinks | 0.6.0 |
| sphinx_rtd_theme | 3.1.0 |
| sphinxcontrib-applehelp | 2.0.0 |
| sphinxcontrib-devhelp | 2.0.0 |
| sphinxcontrib-htmlhelp | 2.1.0 |
| sphinxcontrib-jquery | 4.1 |
| sphinxcontrib-jsmath | 1.0.1 |
| sphinxcontrib-qthelp | 2.0.0 |
| sphinxcontrib-serializinghtml | 2.0.0 |
| sqlparse | 0.4.3 |
| svglib | 1.5.1 |
| tinycss2 | 1.2.1 |
| tomli | 2.3.0 |
| tomlkit | 0.14.0 |
| types-requests | 2.31.0.6 |
| types-setuptools | 81.0.0.20260209 |
| types-urllib3 | 1.26.25.14 |
| typing | 3.7.4.3 |
| typing_extensions | 4.15.0 |
| unidecode | 1.1.2 |
| urllib3 | 2.2.1 |
| userpath | 1.9.2 |
| webencodings | 0.5.1 |
| zipp | 3.23.0 |
