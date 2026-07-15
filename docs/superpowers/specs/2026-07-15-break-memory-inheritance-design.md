# Break Prompt Memory Inheritance Design

Every role in `break-system-prompt/` inherits the same project-memory
structure and policy as `system-prompt/`: the documented `memory/` files are
optional read-only context by default; only an explicit user request permits
writes; writes first read and maintain `memory_index.md`, prefer an existing
matching file, and contain only verified reusable information.

This shared policy does not weaken item isolation: requirement and delivery
artifacts may be created only in the current `R-xxx-*` directory.
