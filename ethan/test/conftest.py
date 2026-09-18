import pathlib
import sys


package_root = pathlib.Path(__file__).resolve().parent.parent
package_root_str = str(package_root)

if package_root_str not in sys.path:
    sys.path.insert(0, package_root_str)
