"""Dependency / call / reference graph.

builder.py : extract import|call|reference|extends|implements|depends edges from AST; resolve
             targets to symbol/file ids where possible (unresolved kept as dst_name); update
             in_degree/out_degree on symbols.
expand.py  : bounded graph walks for retrieval. impact() walks UP (callers/importers) for blast
             radius; how_it_works walks DOWN (callees); find_refs reads direct reverse edges.
"""
