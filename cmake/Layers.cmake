# The engine's layers, lowest first (docs/SERVICE.md). Each is one static library, sub0engine_<layer>, made from src/<layer>/*.cpp with
# headers under include/sub0/engine/<layer>/, and links only the layers below it.
set(SUB0ENGINE_LAYERS platform net contracts evidence backends supervision registry control service)
