# -*- coding: utf-8 -*-

"""A collection of analyses possible on gene lists (of HGNC identifiers) with scores.

For example, this could be applied to the log_2 fold scores from differential gene
expression experiments.

.. warning::

    This module requires the optional dependency ``gseapy``. Install with
    ``pip install gseapy``.
"""


from typing import Any, Dict, Optional, Set, Tuple, Union
from indra.databases import hgnc_client
from pathlib import Path
import logging
import gseapy
import pandas as pd

from indra_cogex.client.enrichment.utils import (
    get_entity_to_regulators,
    get_entity_to_targets,
    get_go,
    get_phenotype_gene_sets,
    get_reactome,
    get_wikipathways, get_statement_metadata_for_pairs,
)
from indra_cogex.client.neo4j_client import Neo4jClient, autoclient

logger = logging.getLogger(__name__)

__all__ = [
    "get_rat_scores",
    "get_mouse_scores",
    "get_human_scores",
    "go_gsea",
    "wikipathways_gsea",
    "reactome_gsea",
    "phenotype_gsea",
    "indra_upstream_gsea",
    "indra_downstream_gsea",
    "gsea",
]


def get_rat_scores(
    path: Union[Path, str, pd.DataFrame],
    gene_symbol_column_name: str,
    score_column_name: str,
    read_csv_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    """Load a differential gene expression file with rat measurements.

    This function extracts the RGD gene symbols, maps them
    to RGD identifiers, uses a custom mapping to orthologs to HGNC,
    then returns the HGNC gene and scores as a dictionary.

    Parameters
    ----------
    path :
        Path to the file to read with :func:`pandas.read_csv` or a DataFrame.
    read_csv_kwargs :
        Keyword arguments to pass to :func:`pandas.read_csv` if path is a file path.
    gene_symbol_column_name :
        The name of the column with gene symbols.
    score_column_name :
        The name of the column with scores.

    Returns
    -------
    :
        A dictionary of mapped orthologous human gene HGNC IDs to scores.
    """
    from indra.databases import rgd_client
    def map_rat_symbol_to_hgnc_id(rat_gene_name: str) -> Union[str, None]:
        rgd_id = rgd_client.get_id_from_name(rat_gene_name)
        return hgnc_client.get_hgnc_from_rat(rgd_id)

    return _get_species_scores(
        func=map_rat_symbol_to_hgnc_id,
        path=path,
        read_csv_kwargs=read_csv_kwargs,
        gene_symbol_column_name=gene_symbol_column_name,
        score_column_name=score_column_name,
    )


def get_mouse_scores(
    path: Union[Path, str, pd.DataFrame],
    gene_symbol_column_name: str,
    score_column_name: str,
    read_csv_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    """Load a differential gene expression file with mouse measurements.

    This function extracts the MGI gene symbols, maps them
    to MGI identifiers, uses a custom mapping to orthologs to HGNC,
    then returns the HGNC gene and scores as a dictionary.

    Parameters
    ----------
    path :
        Path to the file to read with :func:`pandas.read_csv` or a DataFrame.
    read_csv_kwargs :
        Keyword arguments to pass to :func:`pandas.read_csv` if path is a file path.
    gene_symbol_column_name :
        The name of the column with gene symbols.
    score_column_name :
        The name of the column with scores.

    Returns
    -------
    :
        A dictionary of mapped orthologs human gene HGNC IDs to scores.
    """
    from indra.databases import mgi_client
    def map_mouse_symbol_to_hgnc_id(mouse_gene_name: str) -> Union[str, None]:
        mgi_id = mgi_client.get_id_from_name(mouse_gene_name)
        return hgnc_client.get_hgnc_from_mouse(mgi_id)

    return _get_species_scores(
        func=map_mouse_symbol_to_hgnc_id,
        path=path,
        read_csv_kwargs=read_csv_kwargs,
        gene_symbol_column_name=gene_symbol_column_name,
        score_column_name=score_column_name,
    )


def get_human_scores(
    path: Union[Path, str, pd.DataFrame],
    gene_symbol_column_name: str,
    score_column_name: str,
    read_csv_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    """Load a differential gene expression file with human measurements.

    Parameters
    ----------
    path :
        Path to the file to read with :func:`pandas.read_csv` or a DataFrame.
    read_csv_kwargs :
        Keyword arguments to pass to :func:`pandas.read_csv` if path is a file path.
    gene_symbol_column_name :
        The name of the column with gene symbols. If none,
        will try and guess.
    score_column_name :
        The name of the column with scores. If none, will try
        and guess.

    Returns
    -------
    :
        A dictionary of human gene HGNC IDs to scores.
    """
    return _get_species_scores(
        path=path,
        read_csv_kwargs=read_csv_kwargs,
        gene_symbol_column_name=gene_symbol_column_name,
        score_column_name=score_column_name,
        func=hgnc_client.get_current_hgnc_id,
    )


def _get_species_scores(
    path: Union[Path, str, pd.DataFrame],
    gene_symbol_column_name: str,
    score_column_name: str,
    read_csv_kwargs: Optional[Dict[str, Any]] = None,
    *,
    func,
) -> Dict[str, float]:
    """Retrieve species-specific scores from gene expression data.

    Parameters
    ----------
    path : Path, str or pd.DataFrame
        Path to the input file or a DataFrame containing the gene expression data.
    gene_symbol_column_name : str
        The name of the column containing gene symbols.
    score_column_name : str
        The name of the column containing scores associated with the gene symbols.
    read_csv_kwargs : dict of str to Any, optional
        Additional keyword arguments to pass to `pd.read_csv` when reading from a file.
    func : callable
        Function to map gene symbols to HGNC IDs

    Returns
    -------
    dict of str to float
        A dictionary where the keys are HGNC IDs and the values are the associated scores.

    Raises
    ------
    ValueError
        If `gene_symbol_column_name` or `score_column_name` are not found in the DataFrame.
    """
    if read_csv_kwargs is None:
        read_csv_kwargs = {}

    if isinstance(path, pd.DataFrame):
        df = path
    else:
        df = pd.read_csv(path, **read_csv_kwargs)

    if gene_symbol_column_name not in df.columns:
        logger.error("No column named %s in input data", gene_symbol_column_name)
        raise ValueError(f"No column named {gene_symbol_column_name} in input data")
    if score_column_name not in df.columns:
        logger.error("No column named %s in input data", score_column_name)
        raise ValueError(f"No column named {score_column_name} in input data")

    # Here we map from gene symbol (any species) to HGNC ID using the provided function
    df.loc[:, "hgnc_id"] = df[gene_symbol_column_name].map(func)

    # Check if there are any rows after mapping
    if df["hgnc_id"].isna().all():
        logger.error("No HGNC IDs found in input data")
        raise ValueError("No HGNC IDs found in input data")
    df = df.set_index("hgnc_id")
    return df[score_column_name].to_dict()


@autoclient()
def wikipathways_gsea(
    scores: Dict[str, float],
    directory: Union[None, Path, str] = None,
    *,
    client: Neo4jClient,
    **kwargs,
) -> pd.DataFrame:
    """Run GSEA with WikiPathways gene sets.

    Parameters
    ----------
    client :
        The Neo4j client.
    scores :
        A mapping from HGNC gene identifiers to floating point scores
        (e.g., from a differential gene expression analysis)
    directory :
        Specify the directory if the results should be saved, including
        both a dataframe and plots for each gen set
    kwargs :
        Remaining keyword arguments to pass through to :func:`gseapy.prerank`

    Returns
    -------
    :
        A pandas dataframe with the GSEA results
    """
    return gsea(
        gene_sets=get_wikipathways(client=client),
        scores=scores,
        directory=directory,
        **kwargs,
    )


@autoclient()
def reactome_gsea(
    scores: Dict[str, float],
    directory: Union[None, Path, str] = None,
    *,
    client: Neo4jClient,
    **kwargs,
) -> pd.DataFrame:
    """Run GSEA with Reactome gene sets.

    Parameters
    ----------
    client :
        The Neo4j client.
    scores :
        A mapping from HGNC gene identifiers to floating point scores
        (e.g., from a differential gene expression analysis)
    directory :
        Specify the directory if the results should be saved, including
        both a dataframe and plots for each gen set
    kwargs :
        Remaining keyword arguments to pass through to :func:`gseapy.prerank`

    Returns
    -------
    :
        A pandas dataframe with the GSEA results
    """
    return gsea(
        gene_sets=get_reactome(client=client),
        scores=scores,
        directory=directory,
        **kwargs,
    )


@autoclient()
def phenotype_gsea(
    scores: Dict[str, float],
    directory: Union[None, Path, str] = None,
    *,
    client: Neo4jClient,
    **kwargs,
) -> pd.DataFrame:
    """Run GSEA with HPO phenotype gene sets.

    Parameters
    ----------
    client :
        The Neo4j client.
    scores :
        A mapping from HGNC gene identifiers to floating point scores
        (e.g., from a differential gene expression analysis)
    directory :
        Specify the directory if the results should be saved, including
        both a dataframe and plots for each gen set
    kwargs :
        Remaining keyword arguments to pass through to :func:`gseapy.prerank`

    Returns
    -------
    :
        A pandas dataframe with the GSEA results
    """
    return gsea(
        gene_sets=get_phenotype_gene_sets(client=client),
        scores=scores,
        directory=directory,
        **kwargs,
    )


@autoclient()
def go_gsea(
    scores: Dict[str, float],
    directory: Union[None, Path, str] = None,
    *,
    client: Neo4jClient,
    **kwargs,
) -> pd.DataFrame:
    """Run GSEA with gene sets for each Gene Ontology term.

    Parameters
    ----------
    client :
        The Neo4j client.
    scores :
        A mapping from HGNC gene identifiers to floating point scores
        (e.g., from a differential gene expression analysis)
    directory :
        Specify the directory if the results should be saved, including
        both a dataframe and plots for each gen set
    kwargs :
        Remaining keyword arguments to pass through to :func:`gseapy.prerank`

    Returns
    -------
    :
        A pandas dataframe with the GSEA results
    """
    return gsea(
        gene_sets=get_go(client=client),
        scores=scores,
        directory=directory,
        **kwargs,
    )


@autoclient()
def indra_upstream_gsea(
    scores: Dict[str, float],
    directory: Union[None, Path, str] = None,
    *,
    client: Neo4jClient,
    minimum_evidence_count: Optional[int] = None,
    minimum_belief: Optional[float] = None,
    **kwargs,
) -> pd.DataFrame:
    """Run GSEA for each entry in the INDRA database and the set
    of human genes that it regulates.

    Parameters
    ----------
    client :
        The Neo4j client.
    scores :
        A mapping from HGNC gene identifiers to floating point scores
        (e.g., from a differential gene expression analysis)
    directory :
        Specify the directory if the results should be saved, including
        both a dataframe and plots for each gen set
    minimum_evidence_count :
        The minimum number of evidences for a relationship to count it as a regulator.
        Defaults to 1 (i.e., cutoff not applied.
    minimum_belief :
        The minimum belief for a relationship to count it as a regulator.
        Defaults to 0.0 (i.e., cutoff not applied).
    kwargs :
        Remaining keyword arguments to pass through to :func:`gseapy.prerank`

    Returns
    -------
    :
        A pandas dataframe with the GSEA results
    """
    # Set defaults for filtering
    if minimum_evidence_count is None:
        minimum_evidence_count = 1
    if minimum_belief is None:
        minimum_belief = 0.0

    return gsea(
        gene_sets=get_entity_to_targets(
            client=client,
            minimum_evidence_count=minimum_evidence_count,
            minimum_belief=minimum_belief,
        ),
        scores=scores,
        directory=directory,
        client=client,
        minimum_belief=minimum_belief,
        minimum_evidence_count=minimum_evidence_count,
        is_downstream=False,
        **kwargs,
    )


@autoclient()
def indra_downstream_gsea(
    scores: Dict[str, float],
    directory: Union[None, Path, str] = None,
    *,
    client: Neo4jClient,
    minimum_evidence_count: Optional[int] = None,
    minimum_belief: Optional[float] = None,
    **kwargs,
) -> pd.DataFrame:
    """Run GSEA for each entry in the INDRA database and the set
    of human genes that are upstream regulators of it.

    Parameters
    ----------
    client :
        The Neo4j client.
    scores :
        A mapping from HGNC gene identifiers to floating point scores
        (e.g., from a differential gene expression analysis)
    directory :
        Specify the directory if the results should be saved, including
        both a dataframe and plots for each gen set
    minimum_evidence_count :
        The minimum number of evidences for a relationship to count it as a regulator.
        Defaults to 1 (i.e., cutoff not applied.
    minimum_belief :
        The minimum belief for a relationship to count it as a regulator.
        Defaults to 0.0 (i.e., cutoff not applied).
    kwargs :
        Remaining keyword arguments to pass through to :func:`gseapy.prerank`

    Returns
    -------
    :
        A pandas dataframe with the GSEA results
    """
    # Set defaults for filtering
    if minimum_evidence_count is None:
        minimum_evidence_count = 1
    if minimum_belief is None:
        minimum_belief = 0.0

    return gsea(
        gene_sets=get_entity_to_regulators(
            client=client,
            minimum_evidence_count=minimum_evidence_count,
            minimum_belief=minimum_belief,
        ),
        scores=scores,
        directory=directory,
        client=client,
        minimum_belief=minimum_belief,
        minimum_evidence_count=minimum_evidence_count,
        is_downstream=True,
        **kwargs,
    )


GSEA_RETURN_COLUMNS = [
    "Term",
    "Name",
    "ES",
    "NES",
    "NOM p-val",
    "FDR q-val",
    "geneset_size",
    "matched_size",
    "statements"
]


def gsea(
    scores: Dict[str, float],
    gene_sets: Dict[Tuple[str, str], Set[str]],
    directory: Union[None, Path, str] = None,
    alpha: Optional[float] = None,
    keep_insignificant: bool = True,
    # New optional parameters for statement metadata
    client: Optional[Neo4jClient] = None,
    minimum_belief: float = 0.0,
    minimum_evidence_count: int = 1,
    is_downstream: bool = False,
    **kwargs,
) -> pd.DataFrame:
    """Run GSEA on pre-ranked data.

    Parameters
    ----------
    scores :
        A mapping from HGNC gene identifiers to floating point scores
        (e.g., from a differential gene expression analysis)
    gene_sets :
        A mapping from
    directory :
        Specify the directory if the results should be saved, including
        both a dataframe and plots for each gen set
    alpha :
        The cutoff for significance. Defaults to 0.05
    keep_insignificant :
        If false, removes results with a p value less than alpha.
    client :
        Neo4j client for fetching statement metadata (optional)
    minimum_belief :
        Minimum belief score for statement filtering
    minimum_evidence_count :
        Minimum evidence count for statement filtering
    is_downstream :
        Whether this is downstream analysis (gene → regulator)
    kwargs :
        Remaining keyword arguments to pass through to :func:`gseapy.prerank`

    Returns
    -------
    :
        A pandas dataframe with the GSEA results
    """
    if alpha is None:
        alpha = 0.05
    if directory is not None:
        if isinstance(directory, str):
            directory = Path(directory)
        directory.mkdir(exist_ok=True, parents=True)
        directory = directory.as_posix()

    # Extract curie to name mapping and convert gene sets format
    curie_to_name = dict(gene_sets.keys())

    # Convert gene sets from integers to strings to match scores format
    # All gene set functions return integer HGNC IDs, but scores use string HGNC IDs
    curie_to_gene_sets = {
        curie: {str(gene_id) for gene_id in hgnc_gene_ids}
        for (curie, _), hgnc_gene_ids in gene_sets.items()
    }

    # Set default parameters for gseapy
    kwargs.setdefault("permutation_num", 100)
    kwargs.setdefault("format", "svg")

    # Set gene set size limits to allow small and large gene sets
    kwargs.setdefault("min_size", 1)
    kwargs.setdefault("max_size", 50000)

    # Convert gene sets to ensure they're regular sets of strings
    curie_to_gene_sets_final = {
        curie: set(str(gene_id) for gene_id in gene_set)
        for curie, gene_set in curie_to_gene_sets.items()
    }

    # Run GSEA analysis
    res = gseapy.prerank(
        rnk=pd.Series(scores),
        gene_sets=curie_to_gene_sets_final,
        outdir=directory,
        **kwargs,
    )

    # Process results
    # Full column list as of gseapy 1.1.2:
    # Name, Term, ES, NES, NOM p-val, FDR q-val, FWER p-val, Tag %, Gene %,
    # Lead_genes
    rv = res.res2d.reset_index()
    rv["Name"] = rv["Term"].map(curie_to_name)
    rv["matched_size"] = rv['Tag %'].apply(lambda s: s.split('/')[0])
    rv["geneset_size"] = rv['Tag %'].apply(lambda s: s.split('/')[1])

    # Filter columns BEFORE adding statements (statements not in original GSEA_RETURN_COLUMNS)
    base_columns = [col for col in GSEA_RETURN_COLUMNS if col != "statements"]
    rv = rv[base_columns]

    if not keep_insignificant:
        rv = rv[rv["NOM p-val"] < alpha]

    # Add statement metadata AFTER filtering columns but BEFORE final return
    if client is not None and not rv.empty and len(rv) > 0:
        try:
            # Get input genes from scores
            input_genes = set(scores.keys())

            # Build (regulator, gene) pairs for all enriched results
            regulator_gene_pairs = [
                (row["Term"], gene_id)  # Term contains the curie
                for _, row in rv.iterrows()
                for gene_id in input_genes
            ]

            # Fetch statement metadata
            metadata_map = get_statement_metadata_for_pairs(
                regulator_gene_pairs,
                client=client,
                is_downstream=is_downstream,
                minimum_belief=minimum_belief,
                minimum_evidence=minimum_evidence_count
            )

            # Add statements column
            rv["statements"] = rv["Term"].map(lambda curie: metadata_map.get(curie, []))

        except Exception as e:
            # If statement metadata fails, just log and continue without it
            print(f"Warning: Could not fetch statement metadata: {e}")
            rv["statements"] = [[] for _ in range(len(rv))]

    return rv
