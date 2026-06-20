import os
import sys
import subprocess

def verify_submodule():
    """Verify that the mealie-mcp-server submodule is populated.
    If not, attempt to initialize it via git, or guide the user to run setup.py.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mcp_src_dir = os.path.join(base_dir, "mealie-mcp-server", "src")
    mcp_init = os.path.join(mcp_src_dir, "mealie", "__init__.py")
    
    if not os.path.exists(mcp_init):
        print("\n" + "="*80, file=sys.stderr)
        print("CRITICAL ERROR: The 'mealie-mcp-server' submodule is not initialized or populated.", file=sys.stderr)
        print("This submodule is required for the application to function.", file=sys.stderr)
        print("="*80, file=sys.stderr)
        
        # Check if we are in a git repository
        git_dir = os.path.join(base_dir, ".git")
        if os.path.exists(git_dir):
            print("\nDetecting git repository. Attempting auto-initialization...", file=sys.stderr)
            try:
                subprocess.run(
                    ["git", "submodule", "update", "--init", "--recursive"],
                    cwd=base_dir,
                    check=True
                )
                if os.path.exists(mcp_init):
                    print("Submodule successfully initialized!\n", file=sys.stderr)
                    return
            except Exception as e:
                print(f"Failed to auto-initialize submodule via git: {e}", file=sys.stderr)
        
        print("\nTo fix this, please run the setup script:", file=sys.stderr)
        print("    python setup.py", file=sys.stderr)
        print("\nOr initialize it manually with:", file=sys.stderr)
        print("    git submodule update --init --recursive", file=sys.stderr)
        print("="*80 + "\n", file=sys.stderr)
        sys.exit(1)
