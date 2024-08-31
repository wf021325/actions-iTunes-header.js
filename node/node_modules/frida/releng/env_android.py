from configparser import ConfigParser
from pathlib import Path
import shlex
from typing import Callable, Optional

from .machine_file import strv_to_meson
from .machine_spec import MachineSpec


def init_machine_config(machine: MachineSpec,
                        build_machine: MachineSpec,
                        is_cross_build: bool,
                        environ: dict[str, str],
                        toolchain_prefix: Optional[Path],
                        sdk_prefix: Optional[Path],
                        call_selected_meson: Callable,
                        config: ConfigParser,
                        outpath: list[str],
                        outenv: dict[str, str],
                        outdir: Path):
    ndk_found = False
    try:
        ndk_root = Path(environ["ANDROID_NDK_ROOT"])
        if ndk_root.is_absolute():
            ndk_props_file = ndk_root / "source.properties"
            ndk_found = ndk_props_file.exists()
    except:
        pass
    if not ndk_found:
        raise NdkNotFoundError(f"ANDROID_NDK_ROOT must be set to the location of your r{NDK_REQUIRED} NDK")

    if sdk_prefix is not None:
        props = ConfigParser()
        raw_props = ndk_props_file.read_text(encoding="utf-8")
        props.read_string("[source]\n" + raw_props)
        rev = props["source"]["Pkg.Revision"]
        tokens = rev.split(".")
        major_version = int(tokens[0])
        if major_version != NDK_REQUIRED:
            raise NdkVersionError(f"NDK r{NDK_REQUIRED} is required (found r{major_version}, which is unsupported)")

    android_build_os = "darwin" if build_machine.os == "macos" else build_machine.os
    android_build_arch = "x86_64" if build_machine.os in {"macos", "linux"} else build_machine.arch
    android_api = 19 if machine.arch in {"x86", "arm"} else 21

    llvm_bindir = ndk_root / "toolchains" / "llvm" / "prebuilt" / f"{android_build_os}-{android_build_arch}" / "bin"

    binaries = config["binaries"]
    for (identifier, tool_name, *rest) in NDK_BINARIES:
        path = llvm_bindir / f"{tool_name}{build_machine.executable_suffix}"

        argv = [str(path)]
        if len(rest) != 0:
            argv += rest[0]

        raw_val = strv_to_meson(argv)
        if identifier in {"c", "cpp"}:
            raw_val += " + common_flags"

        binaries[identifier] = raw_val

    common_flags = [
        "-target", f"{machine.cpu}-none-linux-android{android_api}",
    ]
    c_like_flags = [
        "-DANDROID",
        "-ffunction-sections",
        "-fdata-sections",
    ]
    cxx_like_flags = []
    cxx_link_flags = [
        "-static-libstdc++",
    ]
    linker_flags = [
        "-Wl,-z,relro",
        "-Wl,-z,noexecstack",
        "-Wl,--gc-sections",
    ]

    read_envflags = lambda name: shlex.split(environ.get(name, ""))

    common_flags += ARCH_COMMON_FLAGS.get(machine.arch, [])
    c_like_flags += ARCH_C_LIKE_FLAGS.get(machine.arch, [])
    c_like_flags += read_envflags("CPPFLAGS")
    linker_flags += ARCH_LINKER_FLAGS.get(machine.arch, [])
    linker_flags += read_envflags("LDFLAGS")

    if android_api < 24:
        cxx_like_flags += ["-D_LIBCPP_HAS_NO_OFF_T_FUNCTIONS"]

    constants = config["constants"]
    constants["common_flags"] = strv_to_meson(common_flags)
    constants["c_like_flags"] = strv_to_meson(c_like_flags)
    constants["linker_flags"] = strv_to_meson(linker_flags)
    constants["cxx_like_flags"] = strv_to_meson(cxx_like_flags)
    constants["cxx_link_flags"] = strv_to_meson(cxx_link_flags)

    options = config["built-in options"]
    options["c_args"] = "c_like_flags + " + strv_to_meson(read_envflags("CFLAGS"))
    options["cpp_args"] = "c_like_flags + cxx_like_flags + " + strv_to_meson(read_envflags("CXXFLAGS"))
    options["c_link_args"] = "linker_flags"
    options["cpp_link_args"] = "linker_flags + cxx_link_flags"
    options["b_lundef"] = "true"


class NdkNotFoundError(Exception):
    pass


class NdkVersionError(Exception):
    pass


NDK_REQUIRED = 25

NDK_BINARIES = [
    ("c",       "clang"),
    ("cpp",     "clang++"),
    ("ar",      "llvm-ar"),
    ("nm",      "llvm-nm"),
    ("ranlib",  "llvm-ranlib"),
    ("strip",   "llvm-strip", ["--strip-all"]),
    ("readelf", "llvm-readelf"),
    ("objcopy", "llvm-objcopy"),
    ("objdump", "llvm-objdump"),
]

ARCH_COMMON_FLAGS = {
    "x86": [
        "-march=pentium4",
    ],
    "arm": [
        "-march=armv7-a",
        "-mfloat-abi=softfp",
        "-mfpu=vfpv3-d16",
    ]
}

ARCH_C_LIKE_FLAGS = {
    "x86": [
        "-mfpmath=sse",
        "-mstackrealign",
    ]
}

ARCH_LINKER_FLAGS = {
    "arm": [
        "-Wl,--fix-cortex-a8",
    ]
}
