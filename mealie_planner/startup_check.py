import os
import sys
import shutil
import subprocess

def run_startup_checks():
    """Verify that the submodule is populated and that default data files are in place."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # 1. Submodule Check
    mcp_src_dir = os.path.join(base_dir, "mealie-mcp-server", "src")
    mcp_init = os.path.join(mcp_src_dir, "mealie", "__init__.py")
    
    if not os.path.exists(mcp_init):
        print("\n" + "="*80, file=sys.stderr)
        print("CRITICAL WARNING: The 'mealie-mcp-server' submodule is not initialized.", file=sys.stderr)
        print("This submodule is required for the application to function.", file=sys.stderr)
        print("="*80, file=sys.stderr)
        
        # Check if we are in a git repository
        git_dir = os.path.join(base_dir, ".git")
        git_executable = shutil.which("git")
        if os.path.exists(git_dir) and git_executable:
            print("\nDetecting git repository. Attempting auto-initialization...", file=sys.stderr)
            try:
                subprocess.run(
                    [git_executable, "submodule", "update", "--init", "--recursive"],
                    cwd=base_dir,
                    check=True
                )
                if os.path.exists(mcp_init):
                    print("Submodule successfully initialized!\n", file=sys.stderr)
                    return
            except Exception as e:
                print(f"Failed to auto-initialize submodule via git: {e}", file=sys.stderr)
        
        print("\nWe will attempt to download the submodule directly...", file=sys.stderr)
        try:
            import urllib.request
            import zipfile
            import tempfile
            
            commit = "f7a2a5e21e68e223629393a5ad16f55dca6ea577"
            url = f"https://github.com/rldiao/mealie-mcp-server/archive/{commit}.zip"
            mcp_dir = os.path.join(base_dir, "mealie-mcp-server")
            os.makedirs(mcp_dir, exist_ok=True)
            
            with tempfile.TemporaryDirectory() as tmpdir:
                zip_path = os.path.join(tmpdir, "submodule.zip")
                urllib.request.urlretrieve(url, zip_path)
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(tmpdir)
                
                extracted_dir = os.path.join(tmpdir, f"mealie-mcp-server-{commit}")
                if not os.path.exists(extracted_dir):
                    dirs = [d for d in os.listdir(tmpdir) if os.path.isdir(os.path.join(tmpdir, d))]
                    if dirs:
                        extracted_dir = os.path.join(tmpdir, dirs[0])
                
                for item in os.listdir(extracted_dir):
                    s = os.path.join(extracted_dir, item)
                    d = os.path.join(mcp_dir, item)
                    if os.path.isdir(s):
                        if os.path.exists(d):
                            shutil.rmtree(d)
                        shutil.copytree(s, d)
                    else:
                        shutil.copy(s, d)
            
            if os.path.exists(mcp_init):
                print("Submodule downloaded and populated successfully!\n", file=sys.stderr)
                return
        except Exception as e:
            print(f"Failed to download submodule: {e}", file=sys.stderr)
            
        print("\nPlease run the setup script to resolve this:", file=sys.stderr)
        print("    python setup.py", file=sys.stderr)
        print("="*80 + "\n", file=sys.stderr)
        sys.exit(1)

    # 2. Data Directory & Examples Check
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    
    dietary_example = os.path.join(base_dir, "dietary_rules.example.txt")
    dietary_target = os.path.join(data_dir, "dietary_rules.txt")
    if os.path.exists(dietary_example) and not os.path.exists(dietary_target):
        try:
            shutil.copy(dietary_example, dietary_target)
            print(f"[*] Initialized default config: {dietary_target}", file=sys.stderr)
        except Exception as e:
            print(f"[!] Warning: Failed to copy dietary rules template: {e}", file=sys.stderr)

    banned_example = os.path.join(base_dir, "banned_recipes.example.txt")
    banned_target = os.path.join(data_dir, "banned_recipes.txt")
    if os.path.exists(banned_example) and not os.path.exists(banned_target):
        try:
            shutil.copy(banned_example, banned_target)
            print(f"[*] Initialized default config: {banned_target}", file=sys.stderr)
        except Exception as e:
            print(f"[!] Warning: Failed to copy banned recipes template: {e}", file=sys.stderr)
