"""The one door to ``libiec61850`` (ADR 0017, ADC-IEC-005).

This is the only module in the repository that imports the protocol library.
The library arrives as the ``pyiec61850-ng`` wheel, which carries the compiled
``libiec61850`` shared object next to a SWIG module. Every call here goes to
the C interface of that shared object through ``ctypes``, not through the
SWIG module, for two reasons that were both observed:

- a SWIG call keeps the interpreter lock while it waits, and the library calls
  back from its own threads, so a client and a server in one process stop
  each other for good;
- the handlers that refuse a write, a setting-group change or a file request
  take C function pointers, which the SWIG module cannot make.

``ctypes`` releases the interpreter lock for the length of a call and turns a
Python function into a C function pointer.

The wheel exists for Linux only. On another system a developer may build the
C library from its source and name the result in ``ADC_LIBIEC61850``; no
automated job does that.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import c_bool, c_char_p, c_float, c_int, c_uint8, c_uint32, c_uint64, c_void_p
from functools import cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

P = c_void_p
ERR = ctypes.POINTER(c_int)

#: C callback types of the handlers the server installs and the client's report handler.
WriteAccessHandler = ctypes.CFUNCTYPE(c_int, P, P, P, P)
PerformCheckHandler = ctypes.CFUNCTYPE(c_int, P, P, P, c_bool, c_bool)
ConnectionHandler = ctypes.CFUNCTYPE(None, P, P, c_bool, P)
FileAccessHandler = ctypes.CFUNCTYPE(c_int, P, P, c_int, c_char_p, c_char_p)
DataSetAccessHandler = ctypes.CFUNCTYPE(c_bool, P, P, c_int, c_char_p)
ControlBlockAccessHandler = ctypes.CFUNCTYPE(c_bool, P, P, c_int, P, P, c_char_p, c_char_p, c_int)
ReportHandler = ctypes.CFUNCTYPE(None, P, P)
GetFileHandler = ctypes.CFUNCTYPE(c_bool, P, P, c_uint32)

#: name -> (result type, argument types). A pointer is always ``c_void_p``.
_SIGNATURES: dict[str, tuple[Any, tuple[Any, ...]]] = {
    "LibIEC61850_getVersionString": (c_char_p, ()),
    # dynamic model
    "IedModel_create": (P, (c_char_p,)),
    "IedModel_destroy": (None, (P,)),
    "LogicalDevice_create": (P, (c_char_p, P)),
    "LogicalNode_create": (P, (c_char_p, P)),
    "DataObject_create": (P, (c_char_p, P, c_int)),
    "DataAttribute_create": (P, (c_char_p, P, c_int, c_int, c_uint8, c_int, c_uint32)),
    "DataSet_create": (P, (c_char_p, P)),
    "DataSetEntry_create": (P, (P, c_char_p, c_int, c_char_p)),
    "ReportControlBlock_create": (
        P,
        (c_char_p, P, c_char_p, c_bool, c_char_p, c_uint32, c_uint8, c_uint8, c_uint32, c_uint32),
    ),
    "SettingGroupControlBlock_create": (P, (P, c_uint8, c_uint8)),
    # server
    "IedServer_create": (P, (P,)),
    "IedServer_destroy": (None, (P,)),
    "IedServer_setLocalIpAddress": (None, (P, c_char_p)),
    "IedServer_start": (None, (P, c_int)),
    "IedServer_stop": (None, (P,)),
    "IedServer_isRunning": (c_bool, (P,)),
    "IedServer_lockDataModel": (None, (P,)),
    "IedServer_unlockDataModel": (None, (P,)),
    "IedServer_updateFloatAttributeValue": (None, (P, P, c_float)),
    "IedServer_updateBooleanAttributeValue": (None, (P, P, c_bool)),
    "IedServer_updateInt32AttributeValue": (None, (P, P, c_int)),
    "IedServer_updateDbposValue": (None, (P, P, c_int)),
    "IedServer_updateVisibleStringAttributeValue": (None, (P, P, c_char_p)),
    "IedServer_updateUTCTimeAttributeValue": (None, (P, P, c_uint64)),
    "IedServer_updateQuality": (None, (P, P, ctypes.c_uint16)),
    "IedServer_updateCtlModel": (None, (P, P, c_int)),
    "IedServer_setWriteAccessPolicy": (None, (P, c_int, c_int)),
    "IedServer_handleWriteAccess": (None, (P, P, WriteAccessHandler, P)),
    "IedServer_setPerformCheckHandler": (None, (P, P, PerformCheckHandler, P)),
    "IedServer_setConnectionIndicationHandler": (None, (P, ConnectionHandler, P)),
    "IedServer_setDataSetAccessHandler": (None, (P, DataSetAccessHandler, P)),
    "IedServer_setControlBlockAccessHandler": (None, (P, ControlBlockAccessHandler, P)),
    "IedServer_getMmsServer": (P, (P,)),
    "MmsServer_installFileAccessHandler": (None, (P, FileAccessHandler, P)),
    "ClientConnection_getPeerAddress": (c_char_p, (P,)),
    "ControlAction_getClientConnection": (P, (P,)),
    "ControlAction_isSelect": (c_bool, (P,)),
    # client
    "IedConnection_createEx": (P, (P, c_bool)),
    "IedConnection_tick": (c_bool, (P,)),
    "IedConnection_getState": (c_int, (P,)),
    "IedConnection_destroy": (None, (P,)),
    "IedConnection_setRequestTimeout": (None, (P, c_uint32)),
    "IedConnection_connectAsync": (None, (P, ERR, c_char_p, c_int)),
    "IedConnection_close": (None, (P,)),
    "IedConnection_getLogicalDeviceList": (P, (P, ERR)),
    "IedConnection_getLogicalDeviceVariables": (P, (P, ERR, c_char_p)),
    "IedConnection_getLogicalDeviceDataSets": (P, (P, ERR, c_char_p)),
    "IedConnection_getDataSetDirectory": (P, (P, ERR, c_char_p, ctypes.POINTER(c_bool))),
    "IedConnection_createDataSet": (None, (P, ERR, c_char_p, P)),
    "IedConnection_getVariableSpecification": (P, (P, ERR, c_char_p, c_int)),
    "IedConnection_readObject": (P, (P, ERR, c_char_p, c_int)),
    "IedConnection_writeObject": (None, (P, ERR, c_char_p, c_int, P)),
    "IedConnection_getRCBValues": (P, (P, ERR, c_char_p, P)),
    "IedConnection_setRCBValues": (None, (P, ERR, P, c_uint32, c_bool)),
    "IedConnection_installReportHandler": (None, (P, c_char_p, c_char_p, ReportHandler, P)),
    "IedConnection_getFileDirectory": (P, (P, ERR, c_char_p)),
    "IedConnection_deleteFile": (None, (P, ERR, c_char_p)),
    "IedConnection_getFile": (c_uint32, (P, ERR, c_char_p, GetFileHandler, P)),
    "IedConnection_setFile": (None, (P, ERR, c_char_p, c_char_p)),
    "ClientReportControlBlock_setRptEna": (None, (P, c_bool)),
    "ClientReportControlBlock_setGI": (None, (P, c_bool)),
    "ClientReportControlBlock_getRptId": (c_char_p, (P,)),
    "ClientReportControlBlock_getDataSetReference": (c_char_p, (P,)),
    "ClientReportControlBlock_destroy": (None, (P,)),
    "ClientReport_getDataSetValues": (P, (P,)),
    "ClientReport_getReasonForInclusion": (c_int, (P, c_int)),
    "ClientReport_getRcbReference": (c_char_p, (P,)),
    # values
    "MmsValue_getType": (c_int, (P,)),
    "MmsValue_getArraySize": (c_uint32, (P,)),
    "MmsValue_getElement": (P, (P, c_int)),
    "MmsValue_toFloat": (c_float, (P,)),
    "MmsValue_toInt32": (c_int, (P,)),
    "MmsValue_toUint32": (c_uint32, (P,)),
    "MmsValue_getBoolean": (c_bool, (P,)),
    "MmsValue_getUtcTimeInMs": (c_uint64, (P,)),
    "MmsValue_getBitStringAsInteger": (c_uint32, (P,)),
    "MmsValue_getBitStringSize": (c_int, (P,)),
    "MmsValue_toString": (c_char_p, (P,)),
    "MmsValue_toInt64": (ctypes.c_int64, (P,)),
    "MmsValue_getDataAccessError": (c_int, (P,)),
    "MmsValue_delete": (None, (P,)),
    "MmsValue_newFloat": (P, (c_float,)),
    "MmsValue_newBoolean": (P, (c_bool,)),
    "MmsValue_newIntegerFromInt32": (P, (c_int,)),
    "MmsValue_newUnsignedFromUint32": (P, (c_uint32,)),
    "MmsValue_newVisibleString": (P, (c_char_p,)),
    "MmsValue_newUtcTimeByMsTime": (P, (c_uint64,)),
    "MmsValue_newBitString": (P, (c_int,)),
    "MmsValue_newOctetString": (P, (c_int, c_int)),
    "MmsValue_createEmptyStructure": (P, (c_int,)),
    "MmsValue_setElement": (None, (P, c_int, P)),
    "MmsVariableSpecification_getType": (c_int, (P,)),
    "MmsVariableSpecification_destroy": (None, (P,)),
    "LinkedList_create": (P, ()),
    "LinkedList_add": (None, (P, P)),
    "LinkedList_getNext": (P, (P,)),
    "LinkedList_getData": (P, (P,)),
    "LinkedList_destroy": (None, (P,)),
    "LinkedList_destroyStatic": (None, (P,)),
}


#: The numbers the C headers of libiec61850 1.6.1 give these names. A test
#: compares each one with the SWIG module of the installed wheel.
CONSTANTS: dict[str, int] = {
    "ACCESS_POLICY_DENY": 1, "ACSI_CLASS_SGCB": 6, "CONTROL_MODEL_DIRECT_NORMAL": 1,
    "CONTROL_OBJECT_ACCESS_DENIED": 3, "DATASET_GET_DIRECTORY": 4, "DATASET_READ": 2,
    "DATA_ACCESS_ERROR_OBJECT_ACCESS_DENIED": 3, "DBPOS_OFF": 1, "DBPOS_ON": 2,
    "IEC61850_BOOLEAN": 0, "IEC61850_CB_ACCESS_TYPE_WRITE": 1, "IEC61850_CHECK": 24,
    "IEC61850_CODEDENUM": 25, "IEC61850_CONSTRUCTED": 27, "IEC61850_ENUMERATED": 12,
    "IEC61850_FC_BL": 10, "IEC61850_FC_BR": 16, "IEC61850_FC_CF": 4, "IEC61850_FC_CO": 12,
    "IEC61850_FC_DC": 5, "IEC61850_FC_EX": 11, "IEC61850_FC_GO": 18, "IEC61850_FC_LG": 17,
    "IEC61850_FC_MS": 14, "IEC61850_FC_MX": 1, "IEC61850_FC_OR": 9, "IEC61850_FC_RP": 15,
    "IEC61850_FC_SE": 7, "IEC61850_FC_SG": 6, "IEC61850_FC_SP": 2, "IEC61850_FC_SR": 8,
    "IEC61850_FC_ST": 0, "IEC61850_FC_SV": 3, "IEC61850_FC_US": 13, "IEC61850_FLOAT32": 10,
    "IEC61850_INT32": 3, "IEC61850_INT8U": 6, "IEC61850_OCTET_STRING_64": 13,
    "IEC61850_QUALITY": 23, "IEC61850_REASON_DATA_CHANGE": 1, "IEC61850_REASON_DATA_UPDATE": 4,
    "IEC61850_REASON_GI": 16, "IEC61850_REASON_INTEGRITY": 8, "IEC61850_REASON_NOT_INCLUDED": 0,
    "IEC61850_REASON_QUALITY_CHANGE": 2, "IEC61850_REASON_UNKNOWN": 32, "IEC61850_TIMESTAMP": 22,
    "IEC61850_VISIBLE_STRING_255": 20, "IED_ERROR_ACCESS_DENIED": 21,
    "IED_ERROR_ALREADY_CONNECTED": 2, "IED_ERROR_CONNECTION_LOST": 3,
    "IED_ERROR_CONNECTION_REJECTED": 5, "IED_ERROR_ENABLE_REPORT_FAILED_DATASET_MISMATCH": 11,
    "IED_ERROR_HARDWARE_FAULT": 29, "IED_ERROR_INVALID_ADDRESS": 28,
    "IED_ERROR_MALFORMED_MESSAGE": 34, "IED_ERROR_NOT_CONNECTED": 1,
    "IED_ERROR_OBJECT_ACCESS_UNSUPPORTED": 24, "IED_ERROR_OBJECT_ATTRIBUTE_INCONSISTENT": 31,
    "IED_ERROR_OBJECT_CONSTRAINT_CONFLICT": 35, "IED_ERROR_OBJECT_DOES_NOT_EXIST": 22,
    "IED_ERROR_OBJECT_EXISTS": 23, "IED_ERROR_OBJECT_INVALIDATED": 33,
    "IED_ERROR_OBJECT_REFERENCE_INVALID": 12, "IED_ERROR_OBJECT_UNDEFINED": 27,
    "IED_ERROR_OBJECT_VALUE_INVALID": 32, "IED_ERROR_OK": 0,
    "IED_ERROR_OUTSTANDING_CALL_LIMIT_REACHED": 6, "IED_ERROR_SERVICE_NOT_IMPLEMENTED": 98,
    "IED_ERROR_SERVICE_NOT_SUPPORTED": 4, "IED_ERROR_TEMPORARILY_UNAVAILABLE": 26,
    "IED_ERROR_TIMEOUT": 20, "IED_ERROR_TYPE_INCONSISTENT": 25, "IED_ERROR_TYPE_UNSUPPORTED": 30,
    "IED_ERROR_UNEXPECTED_VALUE_RECEIVED": 13, "IED_ERROR_UNKNOWN": 99,
    "IED_ERROR_USER_PROVIDED_INVALID_ARGUMENT": 10, "IED_STATE_CLOSED": 0,
    "IED_STATE_CONNECTED": 2, "MMS_ARRAY": 0, "MMS_BIT_STRING": 3,
    "MMS_BOOLEAN": 2, "MMS_DATA_ACCESS_ERROR": 15, "MMS_ERROR_FILE_FILE_ACCESS_DENIED": 96,
    "MMS_FLOAT": 6, "MMS_INTEGER": 4, "MMS_OCTET_STRING": 7, "MMS_STRING": 13, "MMS_STRUCTURE": 1,
    "MMS_UNSIGNED": 5, "MMS_UTC_TIME": 14, "MMS_VISIBLE_STRING": 8,
    "QUALITY_DETAIL_OLD_DATA": 128, "QUALITY_VALIDITY_GOOD": 0, "QUALITY_VALIDITY_INVALID": 2,
    "QUALITY_VALIDITY_QUESTIONABLE": 3, "RCB_ELEMENT_GI": 1024, "RCB_ELEMENT_RPT_ENA": 2,
    "RPT_OPT_DATA_SET": 8, "RPT_OPT_ENTRY_ID": 64, "RPT_OPT_REASON_FOR_INCLUSION": 4,
    "RPT_OPT_SEQ_NUM": 1, "RPT_OPT_TIME_STAMP": 2, "TRG_OPT_DATA_CHANGED": 1, "TRG_OPT_GI": 16,
    "TRG_OPT_QUALITY_CHANGED": 2,
}  # fmt: skip
#: Environment variable naming a libiec61850 shared library built from source.
OVERRIDE = "ADC_LIBIEC61850"
VERSION = "1.6.1"


class LibraryUnavailableError(RuntimeError):
    """The protocol library is not installed on this platform."""


def available() -> bool:
    """Return whether the protocol library can be loaded here."""
    try:
        load()
    except LibraryUnavailableError:
        return False
    return True


def constants() -> Any:
    """Return the library's constants as attributes."""
    return SimpleNamespace(**CONSTANTS)


def _shared_object() -> Path:
    override = os.environ.get(OVERRIDE)
    if override:
        return Path(override)
    try:
        import pyiec61850
    except ImportError as exc:
        raise LibraryUnavailableError(
            "pyiec61850-ng is not installed; it has wheels for Linux only (ADR 0017)"
        ) from exc
    site = Path(pyiec61850.__file__).resolve().parents[1]
    found = sorted((site / "pyiec61850_ng.libs").glob("libiec61850*.so*"))
    if not found:
        raise LibraryUnavailableError(f"no libiec61850 shared object in {site}")
    return found[0]


@cache
def load() -> Any:
    """Load the shared object and declare the functions used.

    Raises:
        LibraryUnavailableError: If there is no library here, or it is not the
            version this module was written against.
    """
    path = _shared_object()
    try:
        lib = ctypes.CDLL(str(path))
        for name, (result, arguments) in _SIGNATURES.items():
            function = getattr(lib, name)
            function.restype, function.argtypes = result, list(arguments)
    except (OSError, AttributeError) as exc:
        raise LibraryUnavailableError(f"cannot use {path}: {exc}") from exc
    found = lib.LibIEC61850_getVersionString().decode()
    if found != VERSION:
        raise LibraryUnavailableError(f"{path} is libiec61850 {found}, not {VERSION}")
    return lib


def version() -> str:
    """Return the version the loaded library reports."""
    return str(load().LibIEC61850_getVersionString().decode())


def strings(linked_list: int | None, static: bool = False) -> list[str]:
    """Copy a library list of C strings and free it."""
    lib = load()
    out: list[str] = []
    if not linked_list:
        return out
    element = lib.LinkedList_getNext(linked_list)
    while element:
        text = ctypes.cast(lib.LinkedList_getData(element), c_char_p).value
        out.append((text or b"").decode())
        element = lib.LinkedList_getNext(element)
    (lib.LinkedList_destroyStatic if static else lib.LinkedList_destroy)(linked_list)
    return out
