# ----------------------------------------------------------------------------
# Copyright (c) 2005-2023, PyInstaller Development Team.
#
# Distributed under the terms of the GNU General Public License (version 2
# or later) with exception for distributing the bootloader.
#
# The full license is in the file COPYING.txt, distributed with this software.
#
# SPDX-License-Identifier: (GPL-2.0-or-later WITH Bootloader-exception)
# ----------------------------------------------------------------------------
import os
from typing import Callable

from PyInstaller import isolated


@isolated.decorate
def django_dottedstring_imports(django_root_dir):
    """
    An isolated helper that returns list of all Django dependencies, parsed from the `mysite.settings` module.

    NOTE: With newer version of Django this is most likely the part of PyInstaller that will be broken.

    Tested with Django 2.2
    """

    import sys
    import os

    import PyInstaller.utils.misc
    from PyInstaller.utils import hooks as hookutils

    # Extra search paths to add to sys.path:
    #  - parent directory of the django_root_dir
    #  - django_root_dir itself; often, Django users do not specify absolute imports in the settings module.
    search_paths = [
        PyInstaller.utils.misc.get_path_to_toplevel_modules(django_root_dir),
        django_root_dir,
    ]
    sys.path += search_paths

    # Set the path to project's settings module
    default_settings_module = os.path.basename(django_root_dir) + '.settings'
    settings_module = os.environ.get('DJANGO_SETTINGS_MODULE', default_settings_module)
    os.environ['DJANGO_SETTINGS_MODULE'] = settings_module

    # Calling django.setup() avoids the exception AppRegistryNotReady() and also reads the user settings
    # from DJANGO_SETTINGS_MODULE.
    # https://stackoverflow.com/questions/24793351/django-appregistrynotready
    import django  # noqa: E402

    django.setup()

    # This allows to access all django settings even from the settings.py module.
    from django.conf import settings  # noqa: E402

    hiddenimports = list(settings.INSTALLED_APPS)


    def _remove_class(class_name):
        return '.'.join(class_name.split('.')[0:-1])

    # Do not fail script when settings does not have such attributes.
    if hasattr(settings, 'TEMPLATE_CONTEXT_PROCESSORS'):
        hiddenimports += list(settings.TEMPLATE_CONTEXT_PROCESSORS)

    if hasattr(settings, 'TEMPLATES'):
        for template in settings.TEMPLATES:
            hiddenimports += list(template.get('OPTIONS', {}).get('context_processors', []))

    if hasattr(settings, 'CACHES'):
        for cache in settings.CACHES.values():
            if cache.get('BACKEND'):
                cl = _remove_class(cache.get('BACKEND'))
                hiddenimports.append(cl)
            client_class = cache.get('OPTIONS', {}).get('CLIENT_CLASS')
            if client_class:
                cl = _remove_class(client_class)
                hiddenimports.append(cl)

    if hasattr(settings, 'STORAGES'):
        for storage in settings.STORAGES.values():
            if storage.get('BACKEND'):
                cl = _remove_class(storage.get('BACKEND'))

    if hasattr(settings, 'TEMPLATE_LOADERS'):
        hiddenimports += list(settings.TEMPLATE_LOADERS)

    hiddenimports += [settings.ROOT_URLCONF]

    #-- Changes in Django 1.7.

    # Remove class names and keep just modules.
    if hasattr(settings, 'AUTHENTICATION_BACKENDS'):
        for cl in settings.AUTHENTICATION_BACKENDS:
            cl = _remove_class(cl)
            hiddenimports.append(cl)
    # Deprecated since 4.2, may be None until it is removed
    cl = getattr(settings, 'DEFAULT_FILE_STORAGE', None)
    if cl:
        hiddenimports.append(_remove_class(cl))
    if hasattr(settings, 'FILE_UPLOAD_HANDLERS'):
        for cl in settings.FILE_UPLOAD_HANDLERS:
            cl = _remove_class(cl)
            hiddenimports.append(cl)
    if hasattr(settings, 'MIDDLEWARE_CLASSES'):
        for cl in settings.MIDDLEWARE_CLASSES:
            cl = _remove_class(cl)
            hiddenimports.append(cl)
    if hasattr(settings, 'MIDDLEWARE'):
        for cl in settings.MIDDLEWARE:
            cl = _remove_class(cl)
            hiddenimports.append(cl)
    # Templates is a dict:
    if hasattr(settings, 'TEMPLATES'):
        for templ in settings.TEMPLATES:
            backend = _remove_class(templ['BACKEND'])
            hiddenimports.append(backend)
            # Include context_processors.
            if hasattr(templ, 'OPTIONS'):
                if hasattr(templ['OPTIONS'], 'context_processors'):
                    # Context processors are functions - strip last word.
                    mods = templ['OPTIONS']['context_processors']
                    mods = [_remove_class(x) for x in mods]
                    hiddenimports += mods
    # Include database backends - it is a dict.
    for v in settings.DATABASES.values():
        hiddenimports.append(v['ENGINE'])

    # Add templatetags and context processors for each installed app.
    for app in settings.INSTALLED_APPS:
        app_templatetag_module = app + '.templatetags'
        app_ctx_proc_module = app + '.context_processors'
        hiddenimports.append(app_templatetag_module)
        hiddenimports += hookutils.collect_submodules(app_templatetag_module)
        hiddenimports.append(app_ctx_proc_module)

    # Deduplicate imports.
    hiddenimports = list(set(hiddenimports))

    # Return the hidden imports
    return hiddenimports


def django_find_root_dir():
    """
    Return path to directory (top-level Python package) that contains main django files. Return None if no directory
    was detected.

    Main Django project directory contain files like '__init__.py', 'settings.py' and 'url.py'.

    In Django 1.4+ the script 'manage.py' is not in the directory with 'settings.py' but usually one level up. We
    need to detect this special case too.
    """
    # 'PyInstaller.config' cannot be imported as other top-level modules.
    from PyInstaller.config import CONF

    # Get the directory with manage.py. Manage.py is supplied to PyInstaller as the first main executable script.
    manage_py = CONF['main_script']
    manage_dir = os.path.dirname(os.path.abspath(manage_py))

    # Get the Django root directory. The directory that contains settings.py and url.py. It could be the directory
    # containing manage.py or any of its subdirectories.
    settings_dir = None
    files = set(os.listdir(manage_dir))
    if ('settings.py' in files or 'settings' in files) and 'urls.py' in files:
        settings_dir = manage_dir
    else:
        for f in files:
            if os.path.isdir(os.path.join(manage_dir, f)):
                subfiles = os.listdir(os.path.join(manage_dir, f))
                # Subdirectory contains critical files.
                if ('settings.py' in subfiles or 'settings' in subfiles) and 'urls.py' in subfiles:
                    settings_dir = os.path.join(manage_dir, f)
                    break  # Find the first directory.

    return settings_dir


def django_collect_submodules(
    package: str,
    filter: Callable[[str], bool] = lambda name: True,
    on_error: str = "warn once",
    isolated_callable = None,
):
    from PyInstaller.utils import hooks as hookutils

    return hookutils.collect_submodules(
        package=package, 
        filter=filter, 
        on_error=on_error,
        isolated_callable=_django_collect_submodules,
    )


def _django_collect_submodules(name, on_error):
    from PyInstaller.utils import hooks as hookutils
    import django  # noqa: E402

    django.setup()
    return hookutils._collect_submodules(name, on_error)