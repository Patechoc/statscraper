# encoding: utf-8

u"""
 This file contains the base class for scrapers. The scraper can navigate
 though an hierarchy of collections and datasets. Collections and datasets
 are refered to as “items”.

       ┏━ Collection ━━━ Collection ━┳━ Dataset
 ROOT ━╋━ Collection ━┳━ Dataset     ┣━ Dataset
       ┗━ Collection  ┣━ Dataset     ┗━ Dataset
                      ┗━ Dataset

 ╰───────────────────────┬─────────────────────╯
                       items

 A scraper can override three methods:
  * _fetch_itemslist(item) yields items at the current position
  * _fetch_dimensions(dataset) yields dimensions available on a dataset
  * _fetch_data(dataset) syield rows from a dataset

 A number of hooks are avaiable for more advanced scrapers. These are called
 by adding the on decorator on a method:

  @on("up")
  def my_method(self):
    # Do something when the user moves up one level

"""
import six
from hashlib import md5
from json import dumps
import pandas as pd
from collections import deque
from copy import deepcopy
from .datatypes import Datatype

try:
    from itertools import ifilter as filter
except ImportError:
    pass

TYPE_DATASET = "Dataset"
TYPE_COLLECTION = "Collection"
ROOT = "<root>"  # Special id for root position
""" Constants for item types and id's """


class NoSuchItem(IndexError):
    """No such Collection or Dataset."""

    pass


class DatasetNotInView(IndexError):
    """Tried to operate on a dataset that is no longer visible."""

    pass


class InvalidData(Exception):
    """The scraper encountered some invalid data."""

    pass


class ResultSet(list):
    """The result of a dataset query.

    This is essentially a list of Result objects.
    """

    _pandas = None
    dataset = None

    @property
    def list_of_dicts(self):
        """Return a list of dictionaries, with the key "value" for values."""
        def merge_two_dicts(x, y):
            z = x.copy()
            z.update(y)
            return z
        return [merge_two_dicts(x.raw_dimensions, {"value": x.value})
                for x in self]

    @property
    def pandas(self):
        """Return a Pandas dataframe."""
        if self._pandas is None:
            self._pandas = pd.DataFrame().from_records(self.list_of_dicts)
        return self._pandas

    def translate(self, dialect):
        """Return a copy of this ResultSet in a different dialect."""
        new_resultset = deepcopy(self)
        new_resultset.dialect = dialect

        for result in new_resultset:
            for dimensionvalue in result.dimensionvalues:
                if dimensionvalue.datatype is not None:
                    print("dimension %s has datatype: %s" % (dimensionvalue, dimensionvalue.datatype))
        return new_resultset

    def append(self, val):
        """Connect any new results to the resultset.

        We will also add a datatype here, so that each result can handle
        validation etc independently. This is so that scraper authors
        don't need to worry about creating and passing around datatype objects.

        As the scraper author yields result objects, we append them to
        a resultset.
        """
        val.resultset = self
        val.dataset = self.dataset

        # Check result dimensions against available dimensions for this dataset
        # for validation and translation
        if val.dataset:
            dataset_dimensions = self.dataset.dimensions
            for k, v in val.raw_dimensions.items():
                if isinstance(v, DimensionValue):
                    val.dimensionvalues.append(v)
                else:
                    if k in self.dataset.dimensions:
                        dim = DimensionValue(v, dataset_dimensions[k])
                    else:
                        dim = DimensionValue(v, Dimension())
                val.dimensionvalues.append(dim)

        super(ResultSet, self).append(val)


class Dimensionslist(list):
    """A one dimensional list of dimensions."""

    def __getitem__(self, key):
        """Make it possible to get dimension by id or identity."""
        if isinstance(key, six.string_types):
            def f(x): return (x.id == key)
        elif isinstance(key, Item):
            def f(x): return (x is key)
        else:
            return list.__getitem__(self, key)
        try:
            val = next(filter(f, self))
            return val
        except IndexError:
            # No such id
            raise NoSuchItem("No such dimension")

    def get(self, key):
        """Provide alias for bracket notation."""
        return self[key]

    def __contains__(self, item):
        """Make it possible to use 'in' keyword with id."""
        if isinstance(item, six.string_types):
            return bool(len(list(filter(lambda x: x.id == item, self))))
        else:
            return super(Itemslist, self).__contains__(item)


class Result(object):
    u"""A “row” in a result.

    A result contains a numerical value,
    and optinlly a set of dimensions with values.
    """
    dimensionvalues = Dimensionslist()

    def __init__(self, value, dimensions={}):
        """Value is supposed, but not strictly required to be numerical."""
        self.value = value
        self.raw_dimensions = dimensions

    def __getitem__(self, key):
        """Make it possible to get dimensions by name."""
        if isinstance(key, six.string_types):
            return self.dimensionvalues[key]
        else:
            return list.__getitem__(self, key)

    def get(self, key):
        """Provide alias for bracket notation."""
        return self[key]

    def __str__(self):
        return str(self.value)

    def __repr__(self):
        return '<Result: %s>' % str(self)


class Dimension(object):
    """A dimension in a dataset."""

    def __init__(self, id_, label=None, allowed_values=None, datatype=None):
        """A single dimension.

        If allowed_values are specified, they will override any
        allowed values for the datatype
        """
        self.id = id_
        self._allowed_values = None
        self.datatype = None
        if label is None:
            self.label = id_
        else:
            self.label = label
        if datatype:
            self.datatype = Datatype(datatype)
            self._allowed_values = self.datatype.allowed_values
        if allowed_values:
            self._allowed_values = allowed_values

    def __str__(self):
        try:
            return self.id.encode("utf-8")
        except UnicodeEncodeError:
            return self.id

    def __repr__(self):
        return '<Dimension: %s (%s)>' % (str(self), self.label.encode("utf-8"))

    @property
    def allowed_values(self):
        """Return a list of allowed values."""
        if self._allowed_values is None:
            self._allowed_values = self.scraper._fetch_allowed_values(self)
        return self._allowed_values


class DimensionValue(object):
    """The value for a dimension inside a Resultset."""

    def __init__(self, value, dimension):
        """Value can be any type. dimension is a Dimension() object."""
        self.value = value
        # FIXME make these getter methods
        self.id = dimension.id
        self.label = dimension.label
        self.datatype = dimension.datatype
        self.allowed_values = dimension.allowed_values
        self.dimension = dimension

    def __str__(self):
        if isinstance(self.value, str):
            return self.value
        return self.value.encode("utf-8")

    def __repr__(self):
        return u'<DimensionValue: %s (%s): %s>' %\
            (self.id.encode("utf-8"), self.label.encode("utf-8"), str(self))


class Itemslist(list):
    """A one dimensional list of items.

    Has some conventience getters and setters for scrapers
    """

    @property
    def type(self):
        """Check if this is a list of Collections or Datasets."""
        try:
            return self[0].type
        except IndexError:
            return None

    def __getitem__(self, key):
        """Make it possible to get item by id, identity or index.

        All of these will work:
         scraper.items[0]
         scraper.items["dataset_1"]
         scraper.items[dataset]
        """
        if isinstance(key, six.string_types):
            def f(x): return (x.id == key)
        elif isinstance(key, Item):
            def f(x): return (x is key)
        else:
            return list.__getitem__(self, key)
        try:
            val = next(filter(f, self))
            return val
        except IndexError:
            # No such id
            raise NoSuchItem("No such item in Itemslist")

    def __contains__(self, item):
        """Make it possible to use 'in' keyword with id."""
        if isinstance(item, six.string_types):
            return bool(len(list(filter(lambda x: x.id == item, self))))
        else:
            return super(Itemslist, self).__contains__(item)

    def get(self, key):
        """Provide alias for bracket notation."""
        return self[key]

    def empty(self):
        """Empty this list (delete all contents)."""
        del self[:]
        return self

    def append(self, val):
        """Connect any new items to the scraper."""
        val.scraper = self.scraper
        super(Itemslist, self).append(val)


class Item(object):
    """Common base class for collections and datasets."""

    parent_ = None  # Populated when added to an itemlist
    _items = None  # Itemslist with children

    def __init__(self, id_, label=None, blob=None):
        self.id = id_
        self.blob = blob
        if label is None:
            self.label = id_
        else:
            self.label = label

    def __str__(self):
        if isinstance(self.id, str):
            return self.id
        return self.id.encode("utf-8")

    @property
    def parent(self):
        """ Return the parent item """
        if self.parent_ is None:
            raise Exception("""\
You tried to access an uninitiated item. \
This should not be possible. Please file a bug report at \
https://github.com/jplusplus/statscraper/issues""")
        return self.parent_

    @property
    def type(self):
        """Check if this is a Collection or Dataset."""
        try:
            if isinstance(self, Collection):
                return TYPE_COLLECTION
            else:
                return TYPE_DATASET
        except IndexError:
            return None


class Collection(Item):
    """A collection can contain collection of datasets."""

    def __repr__(self):
        return '<Collection: %s>' % str(self)

    @property
    def is_root(self):
        """Check if root element."""
        if self.id == ROOT:
            return True
        else:
            return None

    @property
    def items(self):
        """Itemslist of children."""
        if self._items is None:
            self._items = Itemslist()
            self._items.scraper = self.scraper
            for i in self.scraper._fetch_itemslist(self):
                i.parent_ = self
                if i.type == TYPE_DATASET and i.dialect is None:
                    i.dialect = self.scraper.dialect
                self._items.append(i)
        return self._items

    @property
    def children(self):
        """Recuriveky get all descendent datasets."""
        for item in self.items:
            if item.type == TYPE_COLLECTION:
                for child in item.children:
                    yield child
            else:
                yield item

    def __getitem___(self, key):
        """Provide  bracket notation.

        collection["abc"] till return the item with id abc
        """
        try:
            return next(filter(lambda x: x.id == key, self.items))
        except IndexError:
            # No such id
            raise NoSuchItem("No such item in Collection")

    def get(self, key):
        """Provide alias for bracket notation."""
        return self[key]


class Dataset(Item):
    """A dataset. Can be empty."""

    _data = {}  # We store one ResultSet for each unique query
    _dimensions = None
    dialect = None
    query = None

    @property
    def items(self):
        """A dataset has no children."""
        return None

    @property
    def _hash(self):
        """Return a hash for the current query.

        This hash is _not_ a unique representation of the dataset!
        """
        dump = dumps(self.query, sort_keys=True)
        if isinstance(dump, str):
            dump = dump.encode('utf-8')
        return md5(dump).hexdigest()

    def fetch(self, query=None):
        """Ask scraper to return data for the current dataset."""
        if query:
            self.query = query

        hash_ = self._hash
        if hash_ in self._data:
            return self._data[hash_]

        if self.scraper.current_item is not self:
            self._move_here()

        rs = ResultSet()
        rs.dialect = self.dialect
        rs.dataset = self
        for result in self.scraper._fetch_data(self, query=self.query):
            rs.append(result)
        self._data[hash_] = rs
        return self._data[hash_]

    def _move_here(self):
        """Try to move the cursor here, if this item i visible."""
        if self in self.parent.items:
            self.scraper.move_up()

        try:
            self.scraper.move_to(self.id)
        except NoSuchItem:
            raise DatasetNotInView()

    @property
    def data(self):
        """Data as a property, given current query."""
        return self.fetch(query=self.query)

    @property
    def dimensions(self):
        """Available dimensions, if defined."""
        # First of all: Select this dataset
        if self.scraper.current_item is not self:
            self._move_here()

        if self._dimensions is None:
            self._dimensions = Dimensionslist()
            for d in self.scraper._fetch_dimensions(self):
                d.dataset = self
                d.scraper = self.scraper
                self._dimensions.append(d)
        return self._dimensions

    @property
    def shape(self):
        """Compute the shape of the dataset as (rows, cols)."""
        if not self.data:
            return (0, 0)
        return (len(self.data), len(self.dimensions))

    def __repr__(self):
        return '<Dataset: %s>' % str(self)


class BaseScraper(object):
    """The base class for scapers."""

    # Hooks
    _hooks = {
        'init': [],  # Called when initiating the class
        'up': [],  # Called when trying to go up one level
        'top': [],  # Called when moving to top level
        'select': [],  # Called when trying to move to a Collection or Dataset
    }

    dialect = None

    @classmethod
    def on(cls, hook):
        """Hook decorator."""
        def decorator(function_):
            cls._hooks[hook].append(function_)
            return function_
        return decorator

    def __repr__(self):
        return u'<Scraper: %s>' % self.__class__.__name__

    def __init__(self, *args, **kwargs):
        """Initiate with a ROOT collection on top."""
        self.current_item = Collection(ROOT)
        self.current_item.scraper = self
        self._collection_path = deque([self.current_item])
        for f in self._hooks["init"]:
            f(self, *args, **kwargs)

    @property
    def items(self):
        """Itemslist of collections or datasets at the current position.

        None will be returned in case of no further levels
        """
        return self.current_item.items

    def fetch(self, query=None):
        """Let the current item fetch it's data."""
        return self.current_item.fetch(query)

    @property
    def parent(self):
        """Return the item above the current, if any."""
        if len(self._collection_path) > 1:
            return self._collection_path[-2]
        else:
            return None

    @property
    def children(self):
        """Recursively return every dataset below current item."""
        return((self.current_item.children))

    @property
    def path(self):
        """All named collections above, including the current, but not root."""
        steps = list(self._collection_path)
        steps.pop(0)
        return steps

    def move_to_top(self):
        """Move to root item."""
        self.current_item = self._collection_path.popleft()
        self._collection_path.clear()
        self._collection_path.append(self.current_item)
        for f in self._hooks["top"]:
            f(self)
        return self

    def move_up(self):
        """Move up one level in the hierarchy, unless already on top."""
        if len(self._collection_path) > 1:
            self._collection_path.pop()
            self.current_item = self._collection_path[-1]

        for f in self._hooks["up"]:
            f(self)
        if len(self._collection_path) == 1:
            for f in self._hooks["top"]:
                f(self)
        return self

    def move_to(self, id_):
        """Select a child item by id (str), reference or index."""
        try:
            # Move cursor to new item, and reset the cached list of subitems
            self.current_item = self.items[id_]
            self._collection_path.append(self.current_item)
        except (StopIteration, IndexError, NoSuchItem):
            raise NoSuchItem
        for f in self._hooks["select"]:
            f(self)
        return self

    def _fetch_itemslist(self, item):
        """Must be overriden by scraper authors, to yield items.

        Should yield items (Collections or Datasets) at the
        current cursor position. E.g something like this:

        list = get_items(self.current_item)
        for item in list:
            if item.type == "Collection":
                yield Collection(item.id)
            else:
                yield Dataset(item.id)
        """
        raise Exception("This scraper has no method for fetching list items!")

    def _fetch_dimensions(self, dataset):
        """Should be overriden by scraper authors, to yield dimensions."""
        raise Exception("This scraper has no method for fetching dimensions!")

    def _fetch_allowed_values(self, dimension):
        """Can be overriden by scraper authors, to yield allowed values."""
        if self.allowed_values is None:
            yield None
        for allowed_value in self.allowed_values:
            yield allowed_value

    def _fetch_data(self, dataset, query=None):
        """Must be overriden by scraper authors, to yield dataset rows."""
        raise Exception("This scraper has no method for fetching data!")
