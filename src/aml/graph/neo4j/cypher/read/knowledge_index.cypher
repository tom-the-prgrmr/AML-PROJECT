// The vector index of the chunks; no row means it does not exist (columns: state, dimensions).
SHOW INDEXES YIELD name, state, options
WHERE name = 'chunk_embedding'
RETURN state, options.indexConfig['vector.dimensions'] AS dimensions;
