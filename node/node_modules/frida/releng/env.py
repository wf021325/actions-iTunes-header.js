from collections import OrderedDict
from configparser import ConfigParser
from dataclasses import dataclass
import os
from pathlib import Path
import platform
import pprint
import shlex
import shutil
import subprocess
import sys
from typing import Callable, Literal, Optional

from . import env_android, env_apple, env_generic, machine_file
from .machine_file import bool_to_meson, str_to_meson, strv_to_meson
from .machine_spec import MachineSpec


@dataclass
class MachineConfig:
    machine_file: Path
    binpath: list[Path]
    environ: dict[str, str]

    def make_merged_environment(self, source_environ: dict[str, str]) -> dict[str, str]:
        menv = {**source_environ}
        menv.update(self.environ)

        if self.binpath:
            old_path = menv.get("PATH", "")
            old_dirs = old_path.split(os.pathsep) if old_path else []
            menv["PATH"] = os.pathsep.join([str(p) for p in self.binpath] + old_dirs)

        return menv


DefaultLibrary = Literal["shared", "static"]


def call_meson(argv, use_submodule, *args, **kwargs):
    return subprocess.run(query_meson_entrypoint(use_submodule) + argv, *args, **kwargs)


def query_meson_entrypoint(use_submodule):
    if use_submodule:
        return [sys.executable, str(INTERNAL_MESON_ENTRYPOINT)]
    return ["meson"]


def load_meson_config(machine: MachineSpec, flavor: str, build_dir: Path):
    return machine_file.load(query_machine_file_path(machine, flavor, build_dir))


def query_machine_file_path(machine: MachineSpec, flavor: str, build_dir: Path) -> Path:
    return build_dir / f"frida{flavor}-{machine.identifier}.txt"


def detect_default_prefix() -> Path:
    if platform.system() == "Windows":
        return Path(os.environ["ProgramFiles"]) / "Frida"
    return Path("/usr/local")


def generate_machine_configs(build_machine: MachineSpec,
                             host_machine: MachineSpec,
                             environ: dict[str, str],
                             toolchain_prefix: Optional[Path],
                             build_sdk_prefix: Optional[Path],
                             host_sdk_prefix: Optional[Path],
                             call_selected_meson: Callable,
                             default_library: DefaultLibrary,
                             outdir: Path) -> tuple[MachineConfig, MachineConfig]:
    is_cross_build = host_machine != build_machine

    if is_cross_build:
        build_environ = {build_envvar_to_host(k): v for k, v in environ.items() if k not in TOOLCHAIN_ENVVARS}
    else:
        build_environ = environ

    build_config = \
            generate_machine_config(build_machine,
                                    build_machine,
                                    is_cross_build,
                                    build_environ,
                                    toolchain_prefix,
                                    build_sdk_prefix,
                                    call_selected_meson,
                                    default_library,
                                    outdir)

    if is_cross_build:
        host_config = generate_machine_config(host_machine,
                                              build_machine,
                                              is_cross_build,
                                              environ,
                                              toolchain_prefix,
                                              host_sdk_prefix,
                                              call_selected_meson,
                                              default_library,
                                              outdir)
    else:
        host_config = build_config

    return (build_config, host_config)


def generate_machine_config(machine: MachineSpec,
                            build_machine: MachineSpec,
                            is_cross_build: bool,
                            environ: dict[str, str],
                            toolchain_prefix: Optional[Path],
                            sdk_prefix: Optional[Path],
                            call_selected_meson: Callable,
                            default_library: DefaultLibrary,
                            outdir: Path) -> MachineConfig:
    config = ConfigParser(dict_type=OrderedDict)
    config["constants"] = OrderedDict()
    config["binaries"] = OrderedDict()
    config["built-in options"] = OrderedDict()
    config["properties"] = OrderedDict()
    config["host_machine"] = OrderedDict([
        ("system", str_to_meson(machine.system)),
        ("subsystem", str_to_meson(machine.subsystem)),
        ("kernel", str_to_meson(machine.kernel)),
        ("cpu_family", str_to_meson(machine.cpu_family)),
        ("cpu", str_to_meson(machine.cpu)),
        ("endian", str_to_meson(machine.endian)),
    ])

    binaries = config["binaries"]
    builtin_options = config["built-in options"]
    properties = config["properties"]

    outpath = []
    outenv = OrderedDict()
    outdir.mkdir(parents=True, exist_ok=True)

    if machine.is_apple:
        impl = env_apple
    elif machine.os == "android":
        impl = env_android
    else:
        impl = env_generic

    impl.init_machine_config(machine,
                             build_machine,
                             is_cross_build,
                             environ,
                             toolchain_prefix,
                             sdk_prefix,
                             call_selected_meson,
                             config,
                             outpath,
                             outenv,
                             outdir)

    if machine.toolchain_is_msvc:
        builtin_options["b_vscrt"] = str_to_meson(machine.config)

    pkg_config = None
    vala_compiler = None
    if toolchain_prefix is not None:
        toolchain_bindir = toolchain_prefix / "bin"
        exe_suffix = build_machine.executable_suffix

        ninja_binary = toolchain_bindir / f"ninja{exe_suffix}"
        if ninja_binary.exists():
            outenv["NINJA"] = str(ninja_binary)

        for (tool_name, filename_suffix) in {("gdbus-codegen", ""),
                                             ("gio-querymodules", exe_suffix),
                                             ("glib-compile-resources", exe_suffix),
                                             ("glib-compile-schemas", exe_suffix),
                                             ("glib-genmarshal", ""),
                                             ("glib-mkenums", ""),
                                             ("flex", exe_suffix),
                                             ("bison", exe_suffix),
                                             ("nasm", exe_suffix)}:
            tool_path = toolchain_bindir / (tool_name + filename_suffix)
            if tool_path.exists():
                if tool_name == "bison":
                    outenv["BISON_PKGDATADIR"] = str(toolchain_prefix / "share" / "bison")
                    outenv["M4"] = str(toolchain_bindir / f"m4{exe_suffix}")
            else:
                tool_path = shutil.which(tool_name)
            if tool_path is not None:
                binaries[tool_name] = strv_to_meson([str(tool_path)])

        pkg_config_binary = toolchain_bindir / f"pkg-config{exe_suffix}"
        if not pkg_config_binary.exists():
            pkg_config_binary = shutil.which("pkg-config")
        if pkg_config_binary is not None:
            pkg_config = [
                str(pkg_config_binary),
            ]
            if default_library == "static":
                pkg_config += ["--static"]
            if sdk_prefix is not None:
                pkg_config += [f"--define-variable=frida_sdk_prefix={sdk_prefix}"]
            binaries["pkg-config"] = strv_to_meson(pkg_config)

        vala_compiler = detect_toolchain_vala_compiler(toolchain_prefix, build_machine)

    pkg_config_path = shlex.split(environ.get("PKG_CONFIG_PATH", "").replace("\\", "\\\\"))

    if sdk_prefix is not None:
        builtin_options["vala_args"] = strv_to_meson([
            "--vapidir=" + str(sdk_prefix / "share" / "vala" / "vapi")
        ])

        pkg_config_path += [str(sdk_prefix / machine.libdatadir / "pkgconfig")]

        sdk_bindir = sdk_prefix / "bin" / build_machine.os_dash_arch
        if sdk_bindir.exists():
            for f in sdk_bindir.iterdir():
                binaries[f.stem] = strv_to_meson([str(f)])

    if vala_compiler is not None:
        valac, vapidir = vala_compiler
        vala = [
            str(valac),
            f"--vapidir={vapidir}",
        ]
        if pkg_config is not None:
            wrapper = outdir / "frida-pkg-config.py"
            wrapper.write_text(make_pkg_config_wrapper(pkg_config, pkg_config_path), encoding="utf-8")
            vala += [f"--pkg-config={quote(sys.executable)} {quote(str(wrapper))}"]
        binaries["vala"] = strv_to_meson(vala)

    qmake6 = shutil.which("qmake6")
    if qmake6 is not None:
        binaries["qmake6"] = strv_to_meson([qmake6])

    builtin_options["pkg_config_path"] = strv_to_meson(pkg_config_path)

    needs_wrapper = needs_exe_wrapper(build_machine, machine, environ)
    properties["needs_exe_wrapper"] = bool_to_meson(needs_wrapper)
    if needs_wrapper:
        wrapper = find_exe_wrapper(machine, environ)
        if wrapper is not None:
            binaries["exe_wrapper"] = strv_to_meson(wrapper)

    machine_file = outdir / f"frida-{machine.identifier}.txt"
    with machine_file.open("w", encoding="utf-8") as f:
        config.write(f)

    return MachineConfig(machine_file, outpath, outenv)


def needs_exe_wrapper(build_machine: MachineSpec,
                      host_machine: MachineSpec,
                      environ: dict[str, str]) -> bool:
    return not can_run_host_binaries(build_machine, host_machine, environ)


def can_run_host_binaries(build_machine: MachineSpec,
                          host_machine: MachineSpec,
                          environ: dict[str, str]) -> bool:
    if host_machine == build_machine:
        return True

    build_os = build_machine.os
    build_arch = build_machine.arch

    host_os = host_machine.os
    host_arch = host_machine.arch

    if host_os == build_os:
        if build_os == "windows":
            return build_arch == "arm64" or host_arch != "arm64"

        if build_os == "macos":
            if build_arch == "arm64" and host_arch == "x86_64":
                return True

        if build_os == "linux" and host_machine.config == build_machine.config:
            if build_arch == "x86_64" and host_arch == "x86":
                return True

    return environ.get("FRIDA_CAN_RUN_HOST_BINARIES", "no") == "yes"


def find_exe_wrapper(machine: MachineSpec,
                     environ: dict[str, str]) -> Optional[list[str]]:
    qemu_sysroot = environ.get("FRIDA_QEMU_SYSROOT")
    if qemu_sysroot is None:
        return None

    qemu_flavor = "qemu-" + QEMU_ARCHS.get(machine.arch, machine.arch)
    qemu_binary = shutil.which(qemu_flavor)
    if qemu_binary is None:
        raise QEMUNotFoundError(f"unable to find {qemu_flavor}, needed due to FRIDA_QEMU_SYSROOT being set")

    return [qemu_binary, "-L", qemu_sysroot]


def make_pkg_config_wrapper(pkg_config: list[str], pkg_config_path: list[str]) -> str:
    return "\n".join([
        "import os",
        "import subprocess",
        "import sys",
        "",
        "args = [",
        f" {pprint.pformat(pkg_config, indent=4)[1:-1]},",
        "    *sys.argv[1:],",
        "]",
        "env = {",
        "    **os.environ,",
        f"    'PKG_CONFIG_PATH': {repr(os.pathsep.join(pkg_config_path))},",
        "}",
        f"p = subprocess.run(args, env=env)",
        "sys.exit(p.returncode)"
    ])


def detect_toolchain_vala_compiler(toolchain_prefix: Path,
                                   build_machine: MachineSpec) -> Optional[tuple[Path, Path]]:
    datadir = next((toolchain_prefix / "share").glob("vala-*"), None)
    if datadir is None:
        return None

    api_version = datadir.name.split("-", maxsplit=1)[1]

    valac = toolchain_prefix / "bin" / f"valac-{api_version}{build_machine.executable_suffix}"
    vapidir = datadir / "vapi"
    return (valac, vapidir)


def build_envvar_to_host(name: str) -> str:
    if name.endswith("_FOR_BUILD"):
        return name[:-10]
    return name


def quote(s: str) -> str:
    if " " not in s:
        return s
    return "\"" + s.replace("\"", "\\\"") + "\""


class QEMUNotFoundError(Exception):
    pass


INTERNAL_MESON_ENTRYPOINT = Path(__file__).resolve().parent / "meson" / "meson.py"

# Based on mesonbuild/envconfig.py and mesonbuild/compilers/compilers.py
TOOLCHAIN_ENVVARS = {
    # Compilers
    "CC",
    "CXX",
    "CSC",
    "CYTHON",
    "DC",
    "FC",
    "OBJC",
    "OBJCXX",
    "RUSTC",
    "VALAC",
    "NASM",

    # Linkers
    "CC_LD",
    "CXX_LD",
    "DC_LD",
    "FC_LD",
    "OBJC_LD",
    "OBJCXX_LD",
    "RUSTC_LD",

    # Binutils
    "AR",
    "AS",
    "LD",
    "NM",
    "OBJCOPY",
    "OBJDUMP",
    "RANLIB",
    "READELF",
    "SIZE",
    "STRINGS",
    "STRIP",
    "WINDRES",

    # Other tools
    "CMAKE",
    "QMAKE",
    "PKG_CONFIG",
    "PKG_CONFIG_PATH",
    "MAKE",
    "VAPIGEN",
    "LLVM_CONFIG",

    # Deprecated
    "D_LD",
    "F_LD",
    "RUST_LD",
    "OBJCPP_LD",

    # Flags
    "CFLAGS",
    "CXXFLAGS",
    "CUFLAGS",
    "OBJCFLAGS",
    "OBJCXXFLAGS",
    "FFLAGS",
    "DFLAGS",
    "VALAFLAGS",
    "RUSTFLAGS",
    "CYTHONFLAGS",
    "CSFLAGS",
    "LDFLAGS",
}

QEMU_ARCHS = {
    "armeabi": "arm",
    "armhf": "arm",
    "armbe8": "armeb",
    "arm64": "aarch64",
}
