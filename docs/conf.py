# THIS FILE IS EXCLUSIVELY MAINTAINED by the project aedev.project_tpls v0.3.105
"""
configuration file for the Sphinx documentation builder
=======================================================

this file only contains a selection of the most common options. for a full list see the documentation at
`https://www.sphinx-doc.org/en/master/config`__.

recommended section header underlines (see also `https://devguide.python.org/documentation/markup/#sections`__ and
`https://www.sphinx-doc.org/en/master/usage/restructuredtext/basics.html#sections`__):

    # with over-line, for parts
    * with over-line, for chapters
    =, for sections
    -, for subsections
    ^, for sub-subsections
    _, for paragraphs (changed because the double-high-comma cannot be used in docstrings).


ReadTheDocs Server Infrastructure Configuration
===============================================

configure on the ReadTheDocs server (`https://readthedocs.org/dashboard/django_playground/advanced`__)
in the Admin area the following default settings:

    * Settings/Programming Language: **Python**
    * Advanced Settings/Global settings/Default branch: **develop**
    * Advanced Settings/Default settings/Requirements file: **docs/requirements.txt**
    * Advanced Settings/Default settings/Install Project: **check**
    * Advanced Settings/Default settings/Use system packages: **check**

.. note::
    use .readthedocs.yaml to get more actual versions of Python (>3.7 see https://blog.readthedocs.com/default-python-3)
    and Sphinx (>1.8).

"""
import os
import sys
from typing import cast, Any

# import sphinx_rtd_theme    - import not needed (see https://github.com/readthedocs/sphinx_rtd_theme)

from ae.base import URI_SVC_SEP                                     # type: ignore
from aedev.base import PROJECT_VERSION_SEP                          # type: ignore
from aedev.project_vars import ProjectDevVars                       # type: ignore

# add project root path, above of this file (conf.py) and the docs folder, to sys.path
project_path = os.path.dirname(os.path.dirname(cast(str, __file__)))
sys.path.insert(0, project_path)


# -- project information ----------------------------------------------------------------------------------------------
root_pdv = ProjectDevVars(project_path=project_path)
author = root_pdv['STK_AUTHOR']
# copyright = str(datetime.datetime.now().year) + ", " + author
docs_requires = root_pdv.pdv_val('docs_requires')
# language = "en"       # default, also explicitly specified in build_docs.sh in build command option: -D language=en
locale_dirs = []        # disable docs build warning "... locales/en/LC_MESSAGES does not exist"
project = root_pdv['project_desc']
repo_name = root_pdv['project_name']
version = root_pdv['project_version']
repo_group = root_pdv['repo_group']
repo_root = root_pdv['repo_root']


# -- general configuration --------------------------------------------------------------------------------------------
#
# add any Sphinx extension module names here, as strings. they can be extensions coming with Sphinx (named
# 'sphinx.ext.*') or your custom ones.
# ---
# sphinx_rtd_theme is since Sphinx 1.4 no longer integrated (like alabaster)
# sphinx_autodoc_typehints gets automatically used by adding it to tests/requirements.txt
extensions = [
    # 'sphinx.ext.autodoc',         # automatically added by autosummary
    'sphinx.ext.autosummary',
    'sphinx.ext.doctest',           # check doctest (>>>) in docstrings
    'sphinx.ext.viewcode',          # include package module source code
    'sphinx.ext.intersphinx',
    'sphinx.ext.graphviz',
    # 'sphinx.ext.coverage',        # not needed because all covered; test by adding to "make html" the "-b coverage"
    # .. option and then check _build/coverage/python.txt (or add it to index.rst).
    'sphinx.ext.autosectionlabel',  # create refs for all titles, subtitles
]
# --- add the extensions that get installed via pip; remove Sphinx from other sphinx extensions
extensions.extend(_.split(PROJECT_VERSION_SEP)[0] for _ in docs_requires if _.startswith("sphinx_"))

# -- autodoc config
# None==enabled (True failing on RTD builds - replaced with None) - see https://github.com/sphinx-doc/sphinx/issues/5459
ENABLED = None
autodoc_default_options: dict[str, Any] = dict(
    autosummary_generate=ENABLED,
    members=ENABLED,
)
autodoc_default_options['member-order'] = 'bysource'
autodoc_default_options['private-members'] = ENABLED
autodoc_default_options['special-members'] = ENABLED
autodoc_default_options['undoc-members'] = ENABLED
autodoc_default_options['show-inheritance'] = ENABLED
autodoc_default_options['exclude-members'] = ", ".join(
    ('_abc_impl', '_abc_cache', '_abc_negative_cache', '_abc_negative_cache_version', '_abc_registry',
     '__abstractmethods__', '__annotations__', '__atom_members__', '__dict__', '__module__', '__slots__', '__weakref__',
     ))

autosummary_generate = True         # pylint: disable=invalid-name
add_module_names = False            # pylint: disable=invalid-name
add_function_parentheses = True     # pylint: disable=invalid-name
numfig = True                       # pylint: disable=invalid-name

# add any paths that contain templates here, relative to this directory.
# templates_path = ['_templates', '_templates/autosummary']

# list of patterns, relative to source directory, that match files and directories to ignore when looking for source
# files. this pattern also affects html_static_path and html_extra_path.
# exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']
exclude_patterns = ["features_and_examples.rst"]

# example configuration for intersphinx: refer to the Python standard library
# - found at https://www.mankier.com/1/sphinx-all and https://github.com/traverseda/pycraft/blob/master/docs/conf.py.
intersphinx_mapping = dict(
    python=(f"https://docs.python.org/" + ".".join(map(str, sys.version_info[0:2])), None),
    kivy=(f"https://kivy.org/doc/stable/", None),
    ae=(f"https://ae.readthedocs.io/en/latest/", None),
    aedev=(f"https://aedev.readthedocs.io/en/latest/", None),
)

# -- options for HTML output -------------------------------------------------

# the theme to use for HTML and HTML Help pages. see the documentation for a list of builtin themes.
html_theme = 'sphinx_rtd_theme'  # pylint: disable=invalid-name # 'alabaster'

# NEXT TWO VARIABLES TAKEN FROM https://github.com/romanvm/sphinx_tutorial/blob/master/docs/conf.py
# theme options are theme-specific and customize the look and feel of a theme further. for a list of options available
# for each theme, see the documentation.
# alabaster theme options - DON'T WORK WITH sphinx_rtd_theme!!!
if html_theme == 'alabaster':
    html_theme_options = dict(
        gitlab_button=True,
        gitlab_type='star&v=2',  # use v2 button
        gitlab_user=repo_group,
        gitlab_repo=repo_name,
        gitlab_banner=True,
    )

    # custom sidebar templates, maps document names to template names. sidebars configuration for alabaster theme:
    html_sidebars = dict()      # pylint: disable=use-dict-literal
    html_sidebars['**'] = [
        'about.html',
        'navigation.html',
        'searchbox.html',
    ]

elif html_theme == 'sphinx_rtd_theme':
    html_theme_path = ["_themes", ]
    # see https://sphinx-rtd-theme.readthedocs.io/en/latest/configuring.html
    html_theme_options = dict(
        # display_version=True,   # this setting is no longer supported by this theme
        # gitlab_url=f"https://gitlab.com/aedev-group/django_playground/docs/index.rst",
        navigation_depth=-1,
        prev_next_buttons_location='both',
        sticky_navigation=True,
        # removed in V 0.1.68: style_external_links=True,
    )

# prevent RTD build fail error 'contents.rst not found' - see https://github.com/readthedocs/readthedocs.org/issues/2569
master_doc = 'index'    # pylint: disable=invalid-name # Sphinx default is 'index', whereas RTD default is 'contents'


# workaround Kivy bug until fixing PR #7435 get released (with Kivy 2.1.0)
os.environ['KIVY_DOC'] = '1'
os.environ['KIVY_NO_ARGS'] = '1'


keep_warnings = True    # keep docs build warnings inline in the resulting doc/html/pdf
