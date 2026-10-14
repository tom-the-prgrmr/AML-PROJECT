// Cosine vector index over the chunk embeddings. $options is
// {indexConfig: {`vector.dimensions`: n, `vector.similarity_function`: 'cosine'}}, with n taken
// from assistant.embedding.dimensions.
CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS
FOR (c:Chunk) ON (c.embedding)
OPTIONS $options;
