"""This module defines the abstract interface of the cache.

API access to the cache should use this interface,
with no assumptions about the backend storage/retrieval mechanisms.
"""
from abc import ABC, abstractmethod
import io
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union

import attr
from attr.validators import instance_of
import nbformat as nbf

# TODO make these abstract
from jupyter_cache.cache.db import NbCommitRecord, NbStageRecord

NB_VERSION = 4


class CachingError(Exception):
    """An error to raise when adding to the cache fails."""


class RetrievalError(Exception):
    """An error to raise when retrieving from the cache fails."""


class NbValidityError(Exception):
    """Signals a notebook may not be valid to commit.

    For example, because it has not yet been executed.
    """

    def __init__(self, message, nb_bundle, *args, **kwargs):
        self.uri = nb_bundle.uri
        super().__init__(message, *args, **kwargs)


class NbArtifactsAbstract(ABC):
    """Container for artefacts of a notebook execution."""

    @property
    @abstractmethod
    def relative_paths(self) -> List[Path]:
        """Return the list of paths (relative to the notebook folder)."""
        pass

    @abstractmethod
    def __iter__(self) -> Iterable[Tuple[Path, io.BufferedReader]]:
        """Yield the relative path and open files (in bytes mode)"""
        pass


@attr.s(frozen=True, slots=True)
class NbBundleIn:
    """A container for notebooks and their associated data to commit."""

    nb: nbf.NotebookNode = attr.ib(
        validator=instance_of(nbf.NotebookNode), metadata={"help": "the notebook"}
    )
    uri: str = attr.ib(
        validator=instance_of(str), metadata={"help": "the origin URI of the notebook"}
    )
    artifacts: Optional[NbArtifactsAbstract] = attr.ib(
        kw_only=True,
        default=None,
        metadata={"help": "artifacts created during the notebook execution"},
    )
    data: dict = attr.ib(
        kw_only=True,
        factory=dict,
        validator=instance_of(dict),
        metadata={"help": "additional data related to the execution"},
    )


@attr.s(frozen=True, slots=True)
class NbBundleOut:
    """A container for notebooks and their associated data that have been committed."""

    nb: nbf.NotebookNode = attr.ib(
        validator=instance_of(nbf.NotebookNode), metadata={"help": "the notebook"}
    )
    commit: NbCommitRecord = attr.ib(metadata={"help": "the commit record"})
    artifacts: Optional[NbArtifactsAbstract] = attr.ib(
        default=None,
        metadata={"help": "artifacts created during the notebook execution"},
    )


class JupyterCacheAbstract(ABC):
    """An abstract cache for storing pre/post executed notebooks."""

    @abstractmethod
    def clear_cache(self):
        """Clear the cache completely."""
        pass

    @abstractmethod
    def commit_notebook_bundle(
        self, bundle: NbBundleIn, check_validity: bool = True, overwrite: bool = False
    ) -> NbCommitRecord:
        """Commit an executed notebook, returning its commit record.

        Note: non-code source text (e.g. markdown) is not stored in the cache.

        :param bundle: The notebook bundle
        :param check_validity: check that the notebook has been executed correctly,
            by asserting `execution_count`s are consecutive and start at 1.
        :param overwrite: Allow overwrite of commit with matching hash
        :return: The primary key of the commit
        """
        pass

    @abstractmethod
    def commit_notebook_file(
        self,
        path: str,
        uri: Optional[str] = None,
        artifacts: List[str] = (),
        data: Optional[dict] = None,
        check_validity: bool = True,
        overwrite: bool = False,
    ) -> NbCommitRecord:
        """Commit an executed notebook, returning its commit record.

        Note: non-code source text (e.g. markdown) is not stored in the cache.

        :param path: path to the notebook
        :param uri: alternative URI to store in the commit record (defaults to path)
        :param artifacts: list of paths to outputs of the executed notebook.
            Artifacts must be in the same folder as the notebook (or a sub-folder)
        :param data: additional, JSONable, data about the commit
        :param check_validity: check that the notebook has been executed correctly,
            by asserting `execution_count`s are consecutive and start at 1.
        :param overwrite: Allow overwrite of commit with matching hash
        :return: The primary key of the commit
        """
        pass

    @abstractmethod
    def list_commit_records(self) -> List[NbCommitRecord]:
        """Return a list of committed notebook records."""
        pass

    def get_commit_record(self, pk: int) -> NbCommitRecord:
        """Return the record of a commit, by its primary key"""
        pass

    @abstractmethod
    def get_commit_bundle(self, pk: int) -> NbBundleOut:
        """Return an executed notebook bundle, by its primary key"""
        pass

    @abstractmethod
    def commit_artefacts_temppath(self, pk: int) -> Path:
        """Context manager to provide a temporary folder path to the notebook artifacts.

        Note this path is only guaranteed to exist within the scope of the context,
        and should only be used for read/copy operations::

            with cache.commit_artefacts_temppath(1) as path:
                shutil.copytree(path, destination)
        """
        pass

    @abstractmethod
    def match_commit_notebook(self, nb: nbf.NotebookNode) -> NbCommitRecord:
        """Match to an executed notebook, returning its primary key.

        :raises KeyError: if no match is found
        """
        pass

    def match_commit_file(self, path: str) -> NbCommitRecord:
        """Match to an executed notebook, returning its primary key.

        :raises KeyError: if no match is found
        """
        notebook = nbf.read(path, NB_VERSION)
        return self.match_commit_notebook(notebook)

    @abstractmethod
    def merge_match_into_notebook(
        self,
        nb: nbf.NotebookNode,
        nb_meta=("kernelspec", "language_info", "widgets"),
        cell_meta=None,
    ) -> Tuple[int, nbf.NotebookNode]:
        """Match to an executed notebook and return a merged version

        :param nb: The input notebook
        :param nb_meta: metadata keys to merge from the commit (all if None)
        :param cell_meta: cell metadata keys to merge from the commit (all if None)
        :raises KeyError: if no match is found
        :return: pk, input notebook with committed code cells and metadata merged.
        """
        pass

    def merge_match_into_file(
        self,
        path: str,
        nb_meta=("kernelspec", "language_info", "widgets"),
        cell_meta=None,
    ) -> Tuple[int, nbf.NotebookNode]:
        """Match to an executed notebook and return a merged version

        :param path: The input notebook path
        :param nb_meta: metadata keys to merge from the commit (all if None)
        :param cell_meta: cell metadata keys to merge from the commit (all if None)
        :raises KeyError: if no match is found
        :return: pk, input notebook with committed code cells and metadata merged.
        """
        nb = nbf.read(path, NB_VERSION)
        return self.merge_match_into_notebook(nb, nb_meta, cell_meta)

    @abstractmethod
    def diff_nbnode_with_commit(
        self, pk: int, nb: nbf.NotebookNode, uri: str = "", as_str=False, **kwargs
    ) -> Union[str, dict]:
        """Return a diff of a notebook to a committed one.

        Note: this will not diff markdown content, since it is not stored in the cache.
        """
        pass

    def diff_nbfile_with_commit(
        self, pk: int, path: str, as_str=False, **kwargs
    ) -> Union[str, dict]:
        """Return a diff of a notebook to a committed one.

        Note: this will not diff markdown content, since it is not stored in the cache.
        """
        nb = nbf.read(path, NB_VERSION)
        return self.diff_nbnode_with_commit(pk, nb, uri=path, as_str=as_str, **kwargs)

    @abstractmethod
    def stage_notebook_file(self, uri: str, assets: List[str] = ()) -> NbStageRecord:
        """Stage a single notebook for execution.

        :param uri: The path to the file
        :param assets: The path of files required by the notebook to run.
        :raises ValueError: assets not within the same folder as the notebook URI.
        """
        pass

    @abstractmethod
    def discard_staged_notebook(self, uri_or_pk: Union[int, str]):
        """Discard a staged notebook."""
        pass

    @abstractmethod
    def list_staged_records(self) -> List[NbStageRecord]:
        """list staged notebook URI's in the cache."""
        pass

    @abstractmethod
    def get_staged_record(self, uri_or_pk: Union[int, str]) -> NbStageRecord:
        """Return the record of a staged notebook, by its primary key or URI."""
        pass

    @abstractmethod
    def get_staged_notebook(self, uri_or_pk: Union[int, str]) -> NbBundleIn:
        """Return a single staged notebook, by its primary key or URI."""
        pass

    @abstractmethod
    def get_commit_record_of_staged(
        self, uri_or_pk: Union[int, str]
    ) -> Optional[NbCommitRecord]:
        pass

    @abstractmethod
    def list_nbs_to_exec(self) -> List[NbStageRecord]:
        """List staged notebooks, whose hash is not present in the cache commits."""
        pass

    # removed until defined use case
    # @abstractmethod
    # def get_commit_codecell(self, pk: int, index: int) -> nbf.NotebookNode:
    #     """Return a code cell from a committed notebook.

    #     NOTE: the index **only** refers to the list of code cells, e.g.
    #     `[codecell_0, textcell_1, codecell_2]`
    #     would map {0: codecell_0, 1: codecell_2}
    #     """
    #     pass