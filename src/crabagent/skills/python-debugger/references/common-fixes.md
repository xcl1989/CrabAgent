# Common Python Fixes

## TypeError: 'NoneType' object is not subscriptable
- Check if a function returns None unexpectedly
- Add proper None checks before accessing attributes/items

## ImportError / ModuleNotFoundError
- Check if the module is installed: `pip list | grep <module>`
- Check for circular imports (A imports B, B imports A)
- Verify `__init__.py` exists in the package directory

## KeyError
- Use `.get(key, default)` instead of `dict[key]`
- Check if the key exists with `in` operator before access

## RecursionError
- Check for missing base case in recursive functions
- Verify the recursive call moves toward the base case

## UnicodeDecodeError
- Specify encoding explicitly: `open(file, encoding='utf-8')`
- Use `errors='replace'` for non-critical reads

## AttributeError: module has no attribute
- Check for name shadowing (file named same as stdlib module)
- Verify the import path is correct
- Check if the attribute was added in a newer Python version
