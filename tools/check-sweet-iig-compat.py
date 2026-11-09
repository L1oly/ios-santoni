#!/usr/bin/env python3
"""Regression vectors for the generated-code-only IORPC compatibility adapter."""
import importlib.util
from pathlib import Path

path = Path(__file__).with_name("sweet-iig-compat.py")
spec = importlib.util.spec_from_file_location("iig_compat", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

# Dispatch table: the content header of the incoming request.
old = "IORPCMessage * msg = IORPCMessageFromMach(rpc.message, false);\n"
assert module.normalize("IORPCMessage * msg = rpc.kernelContent;\n") == old

# Typed invoke path: old iig read the Msg's trailing content member. Both are
# the same address, immediately after the Mach descriptors.
old_content = ("const IOEventLink_Create_Msg_Content * messageContent = "
               "(const IOEventLink_Create_Msg_Content *)"
               "IORPCMessageFromMach((IORPCMessageMach *)(uintptr_t)rpc.message, false);\n")
assert module.normalize(
    "const IOEventLink_Create_Msg_Content * messageContent = rpc.kernelContent;\n"
) == old_content
old_struct_content = ("const struct IOEventLink_Create_Msg_Content * messageContent = "
                      "(const struct IOEventLink_Create_Msg_Content *)"
                      "IORPCMessageFromMach((IORPCMessageMach *)(uintptr_t)rpc.message, false);\n")
assert module.normalize(
    "const struct IOEventLink_Create_Msg_Content * messageContent = rpc.kernelContent;\n"
) == old_struct_content

# IODispatchSource::CheckForWork validates the received reply and its reply
# content, not the original request.
assert module.normalize("message = rpc.kernelContent;\n") == \
    "message = IORPCMessageFromMach(rpc.reply, false);\n"
assert module.normalize("replyMessage = rpc.rpc.kernelContent;\n") == \
    "replyMessage = IORPCMessageFromMach(rpc.rpc.reply, false);\n"

# InterruptOccurred's extra bookkeeping for the newer dispatcher is unused by
# the old ABI and must not leave a call expression on the left of an equals.
assert module.normalize(
    "    rpc.kernelContent = &msg->content.__hdr;\n    memset(msg, 0, sizeof(*msg));\n"
) == "    memset(msg, 0, sizeof(*msg));\n"

# Initializer-only use of the extra member is dropped; the old IORPC layout
# ends at replySize.
old_init = "IORPC rpc = { .message = &buf.msg.mach, .replySize = sizeof(buf.rpl) };\n"
new_init = old_init.replace("sizeof(buf.rpl)", "sizeof(buf.rpl), .kernelContent = &buf.msg.content.__hdr")
assert module.normalize(new_init) == old_init

# Old output is unchanged, and repeated wrapping is harmless.
assert module.normalize(old + old_content) == old + old_content
assert module.normalize(module.normalize(new_init)) == old_init

# Unknown content uses must fail closed rather than guess an ABI mapping.
for unknown in (
    "IORPC rpc = {.kernelContent = unknown()};\n",
    "foo(rpc.kernelContent);\n",
    "rpc.kernelContent = something_else;\n",
):
    try:
        module.normalize(unknown)
    except ValueError:
        pass
    else:
        raise AssertionError("Unknown generated ABI usage must fail closed: " + unknown)
print("PASS: generated IORPC compatibility, old output identity, idempotence and unknown-use rejection")
