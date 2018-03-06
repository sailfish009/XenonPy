# Copyright 2017 TsumiNa. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import re
from collections import defaultdict
from datetime import datetime as dt
from os import remove
from os.path import getmtime
from pathlib import Path
from shutil import rmtree
from urllib.parse import urlparse, urljoin
from warnings import warn

import pandas as pd
import requests
from sklearn.externals import joblib

from .functional import absolute_path
from .. import __cfg_root__
from .._conf import get_dataset_url, get_data_loc


class Loader(object):
    """
    Load data from embed dataset in XenonPy's or user create data saved in ``~/.xenonpy/cached`` dir.
    Also can fetch data by http request.

    This is sample to demonstration how to use is. Also see parameters documents for details.

    ::

        >>> load = Loader()
        >>> elements = load('elements')
        >>> elements.info()
        <class 'pandas.core.frame.DataFrame'>
        Index: 118 entries, H to Og
        Data columns (total 74 columns):
        atomic_number                    118 non-null int64
        atomic_radius                    88 non-null float64
        atomic_radius_rahm               96 non-null float64
        atomic_volume                    91 non-null float64
        atomic_weight                    118 non-null float64
        boiling_point                    96 non-null float64
        brinell_hardness                 59 non-null float64
        bulk_modulus                     69 non-null float64
        ...
    """

    dataset = (
        'elements', 'elements_completed', 'mp_inorganic',
        'electron_density', 'sample_A', 'mp_structure'
    )
    # set to check params

    def __init__(self, location=None):
        """

        Parameters
        ----------
        location: str
            Where data are.
            None(default) means to load data in ``~/.xenonpy/cached`` or ``~/.xenonpy/dataset`` dir.
            When given as url, later can be uesd to fetch files under this url from http-request.
        """
        self.location = location
        self.type = self._select(location)
        self.dataset_dir = Path().home() / __cfg_root__ / 'dataset'
        self.cached_dir = Path().home() / __cfg_root__ / 'cached'

    def _select(self, loc):
        if loc is None:
            return 'local'

        if not isinstance(loc, str):
            raise TypeError('parameter `location` must be string but got {}'.format(type(loc)))

        # local
        scheme = urlparse(loc).scheme
        if scheme is '':
            self.location = absolute_path(loc)
            return 'user_loc'

        # http
        http_schemes = ('http', 'https')
        if scheme in http_schemes:
            return 'http'

        raise ValueError('can not parse location {}'.format(loc))

    def _http_data(self, url, params=None, save_to=None, **kwargs):
        r = requests.get(url, params, **kwargs)
        r.raise_for_status()

        if 'filename' in r.headers:
            filename = r.headers['filename']
        else:
            filename = url.split('/')[-1]

        if save_to is None:
            save_to = str(self.cached_dir / filename)
        with open(save_to, 'wb') as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if chunk:  # filter out keep-alive new chunks
                    f.write(chunk)

        return save_to

    def __call__(self, data=None, **kwargs):
        """
        Same to self.load()
        """
        return self.load(data=data, **kwargs)

    def load(self, data=None, **kwargs):
        """
        load data.

        .. note::
            Try to load data from local at ``~/.xenonpy/dataset``.
            If no data, try to fetch them from remote repository.

        Args
        -----------
        data: str
            name of data.

        Returns
        ------
        ret:DataFrame or Saver or local file path.
        """

        kwargs = dict(kwargs, data=data)

        def _get_data(key, ignore_err=False, del_key=True):
            try:
                ret = kwargs[key]
                if del_key:
                    del kwargs[key]
                return ret
            except KeyError:
                if ignore_err:
                    return None
                else:
                    raise ValueError('need `{}` but got None'.format(key))

        if self.type == 'local':
            data = _get_data('data')
            if data in self.dataset:
                dataset = self.dataset_dir / (data + '.pkl.pd_')
                # fetch data from source if not in local
                if not dataset.exists():
                    self._http_data(get_dataset_url(data), save_to=str(dataset))
                return pd.read_pickle(str(dataset))
            return DataSet(data, ignore_err=False)

        if self.type == 'user_local':
            data = _get_data('data')
            return DataSet(data, path=self.location, ignore_err=False)

        if self.type == 'http':
            data = _get_data('data', ignore_err=True)
            params = _get_data('params', ignore_err=True)
            kwargs['stream'] = True
            url = urljoin(self.location, data)
            return self._http_data(url, params=params, **kwargs)

        raise ValueError('can not fetch data')

    def _get_prop(self, name):
        tmp = self.type
        self.type = 'local'
        ret = self(name)
        self.type = tmp
        return ret

    @property
    def elements(self):
        """
        Element properties from embed dataset.
        These properties are summarized from `mendeleev`_, `pymatgen`_, `CRC Handbook`_ and `magpie`_.

        See Also: :doc:`dataset`

        .. _mendeleev: https://mendeleev.readthedocs.io
        .. _pymatgen: http://pymatgen.org/
        .. _CRC Handbook: http://hbcponline.com/faces/contents/ContentsSearch.xhtml
        .. _magpie: https://bitbucket.org/wolverton/magpie

        Returns
        -------
        DataFrame:
            element properties in pd.DataFrame
        """
        return self._get_prop('elements')

    @property
    def elements_completed(self):
        """
        Completed element properties. [MICE]_ imputation used

        .. [MICE] `Int J Methods Psychiatr Res. 2011 Mar 1; 20(1): 40–49.`__
                    doi: `10.1002/mpr.329 <10.1002/mpr.329>`_

        .. __: https://www.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi?dbfrom=pubmed&retmode=ref&cmd=prlinks&id=21499542

        See Also: :doc:`dataset`

        Returns
        -------
            imputed element properties in pd.DataFrame
        """
        return self._get_prop('elements_completed')


class DataSet(object):
    """
    Save data in a convenient way:

    .. code:: python

        import numpy as np
        np.random.seed(0)

        # some data
        data1 = np.random.randn(5, 5)
        data2 = np.random.randint(5, 5)

        # init Saver
        save = Saver('you_dataset_name')

        # save data
        save(data1, data2)

        # retriever data
        date = save.last()  # last saved
        data = save[0]  # by index
        for data in save:  # as iterator
            do_something(data)

        # delete data
        save.delete(0)  # by index
        save.delete()  # delete 'you_dataset_name' dir

    See Also: :doc:`dataset`
    """

    def __init__(self, name=None, *, path=None, ignore_err=True, backend=joblib):
        """
        Parameters
        ----------
        name: str
            Name of dataset. Usually this is dir name contains data.
        path: str
            Absolute dir path.
        ignore_err: bool
            Ignore ``FileNotFoundError``.
        """
        self._backend = backend
        self._name = name
        if path is not None:
            self._path = Path(absolute_path(path, ignore_err)) / name
        else:
            self._path = Path(get_data_loc('userdata')) / name
        if not self._path.exists():
            if not ignore_err:
                raise FileNotFoundError()
            self._path.mkdir(parents=True)
        self._files = None
        self._make_file_index()

    @property
    def name(self):
        return self._name

    @property
    def path(self):
        return str(self._path.parent)

    def _make_file_index(self):
        self._files = defaultdict(list)
        files = [f for f in self._path.iterdir() if f.match('*.pkl.*')]

        for f in files:
            # select data
            fn = '.'.join(f.name.split('.')[:-3])

            # for compatibility
            # fixme: will be removed at future
            if fn == 'unnamed':
                warn('file like `unnamed.@x` will be renamed to `@x`.', RuntimeWarning)
                new_name = '.'.join(f.name.split('.')[-3:])
                new_path = f.parent / new_name
                f.rename(new_path)
                f = new_path

            if fn == '':
                fn = 'unnamed'
            self._files[fn].append(f)

        for fs in self._files.values():
            if fs is not None:
                fs.sort(key=lambda f: getmtime(str(f)))

    def _load_data(self, file):
        if file.suffix == '.pd_':
            return pd.read_pickle(str(file))
        else:
            return self._backend.load(str(file))

    def _save_data(self, data, filename):
        self._path.mkdir(parents=True, exist_ok=True)
        if isinstance(data, pd.DataFrame):
            file = self._path / (filename + '.pkl.pd_')
            pd.to_pickle(data, str(file))
        else:
            file = self._path / (filename + '.pkl.z')
            self._backend.dump(data, str(file))

        return file

    def dump(self, fpath: str, *,
             rename: str = None,
             with_datetime: bool = True):
        """
        Dump last checked dataset to file.

        Parameters
        ----------
        fpath: str
            Where save to.
        rename: str
            Rename pickle file. Omit to use dataset as name.
        with_datetime: bool
            Suffix file name with dumped time.

        Returns
        -------
        ret: str
            File path.
        """
        ret = {k: self._load_data(v[-1]) for k, v in self._files.items()}
        name = rename if rename else self._name
        if with_datetime:
            datetime = dt.now().strftime('-%Y-%m-%d_%H-%M-%S_%f')
        else:
            datetime = ''
        path_dir = Path(fpath).expanduser()
        if not path_dir.exists():
            path_dir.mkdir(parents=True, exist_ok=True)
        path = path_dir / (name + datetime + '.pkl.z')
        self._backend.dump(ret, str(path))

        return str(path)

    def last(self, name: str = None):
        """
        Return last saved data.

        Args
        ----
        name: str
            Data's name. Omit for access temp data

        Return
        -------
        ret:any python object
            Data stored in `*.pkl` file.
        """
        if name is None:
            return self._load_data(self._files['unnamed'][-1])
        return self._load_data(self._files[name][-1])

    def rm(self, index, name: str = None):
        """
        Delete file(s) with given index.

        Parameters
        ----------
        index: int or slice
            Index of data. Data sorted by datetime.
        name: str
            Data's name. Omit for access unnamed data.
        """

        if not name:
            files = self._files['unnamed'][index]
            if not isinstance(files, list):
                remove(str(files))
            else:
                for f in files:
                    remove(str(f))
            del self._files['unnamed'][index]
            return

        files = self._files[name][index]
        if not isinstance(files, list):
            remove(str(files))
        else:
            for f in files:
                remove(str(f))
        del self._files[name][index]

    def clean(self, name: str = None):
        """
        Remove all data by name. Omit to remove hole dataset.

        Parameters
        ----------
        name: str
            Data's name.Omit to remove hole dataset.
        """
        if name is None:
            rmtree(str(self._path))
            self._files = list()
            self._files = defaultdict(list)
            return

        for f in self._files[name]:
            remove(str(f))
        del self._files[name]

    def __getattr__(self, name):
        """
        Returns sub-dataset.

        Parameters
        ----------
        name: str
            Dataset name.

        Returns
        -------
        self
        """
        sub_set = DataSet(name, path=str(self._path), backend=self._backend)
        setattr(self, name, sub_set)
        return sub_set

    def __repr__(self):
        cont_ls = ['"{}" include:'.format(self._name)]

        for k, v in self._files.items():
            cont_ls.append('"{}": {}'.format(k, len(v)))

        return '\n'.join(cont_ls)

    def __getitem__(self, item):

        # load file
        def _load_file(files, item_):
            _files = files[item_]
            if not isinstance(_files, list):
                return self._load_data(_files)
            return [self._load_data(f) for f in _files]

        if isinstance(item, tuple):
            try:
                key, index = item
            except ValueError:
                raise ValueError('except 2 parameters. [str, int or slice]')
            if not isinstance(key, str) or \
                    (not isinstance(index, int) and not isinstance(index, slice)):
                raise ValueError('except 2 parameters. [str, int or slice]')
            return _load_file(self._files[key], index)

        if isinstance(item, str):
            return self.__getitem__((item, slice(None, None, None)))

        return _load_file(self._files['unnamed'], item)

    def __call__(self, *unnamed_data, **named_data):
        """
        Same to self.save()
        """
        self.save(*unnamed_data, **named_data)

    def save(self, *unnamed_data, **named_data):
        """
        Save data with or without name.
        Data with same name will not be overwritten.

        Parameters
        ----------
        unnamed_data: any object
            Unnamed data.
        named_data: dict
            Named data as k,v pair.

        """
        def _get_file_index(fn):
            if len(self._files[fn]) != 0:
                return int(re.findall(r'@\d+\.', str(self._files[fn][-1]))[-1][1:-1])
            return 0

        num = 0
        for d in unnamed_data:
            if num == 0:
                num = _get_file_index('unnamed')
            num += 1
            f = self._save_data(d, '@' + str(num))
            self._files['unnamed'].append(f)

        for k, v in named_data.items():
            num = _get_file_index(k) + 1
            f = self._save_data(v, k + '.@' + str(num))
            self._files[k].append(f)

