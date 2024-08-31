let getHeader = null;

async function init() {
    // 获取 iTunes 基址
    const itunesBase = Process.enumerateModulesSync()[0].base;
    const cfAllocator = itunesBase.add(0x22A8448).readPointer();
    const kbsyncContext = itunesBase.add(0x22A6BBC).readU32();

    // 声明 NativeFunction
    const CFURLCreateWithBytes = new NativeFunction(Module.findExportByName('CoreFoundation', 'CFURLCreateWithBytes'), 'pointer', ['pointer', 'pointer', 'int64', 'int64', 'int64']);
    const CFDictionaryGetCount = new NativeFunction(Module.findExportByName('CoreFoundation', 'CFDictionaryGetCount'), 'int64', ['pointer']);
    const CFStringGetCString = new NativeFunction(Module.findExportByName('CoreFoundation', 'CFStringGetCString'), 'int8', ['pointer', 'pointer', 'int64', 'int64']);
    const CFStringGetLength = new NativeFunction(Module.findExportByName('CoreFoundation', 'CFStringGetLength'), 'int64', ['pointer']);
    const CFDictionaryGetKeysAndValues = new NativeFunction(Module.findExportByName('CoreFoundation', 'CFDictionaryGetKeysAndValues'), 'void', ['pointer', 'pointer', 'pointer']);
    const CFDataGetBytePtr = new NativeFunction(Module.findExportByName('CoreFoundation', 'CFDataGetBytePtr'), 'pointer', ['pointer']);
    const CFDataGetLength = new NativeFunction(Module.findExportByName('CoreFoundation', 'CFDataGetLength'), 'uint64', ['pointer']);

    // 将 CFString 转换为 JavaScript 字符串
    const readCFStr = (cfs) => {
        const length = CFStringGetLength(cfs);
        const buffer = Memory.alloc(length + 1);
        CFStringGetCString(cfs, buffer, length + 1, 134217984);
        return Memory.readUtf8String(buffer);
    };

    // 将 CFDictionary 转换为 JavaScript 对象
    const readCFDict = (dict) => {
        const count = CFDictionaryGetCount(dict);
        const keys = Memory.alloc(count * Process.pointerSize);
        const values = Memory.alloc(count * Process.pointerSize);
        CFDictionaryGetKeysAndValues(dict, keys, values);

        const result = {};
        for (let i = 0; i < count; i++) {
            const key = readCFStr(keys.add(i * Process.pointerSize).readPointer());
            const value = readCFStr(values.add(i * Process.pointerSize).readPointer());
            result[key] = value;
        }
        return result;
    };

    // 从指针读取数据
    const readCFData = (dataPtr) => {
        if (dataPtr.isNull()) return null;
        const length = CFDataGetLength(dataPtr);
        const buffer = CFDataGetBytePtr(dataPtr);
        return buffer.readByteArray(length);
    };

    // 声明更多 NativeFunction
    const prepareAppleHdrWrap = new NativeFunction(itunesBase.add(0x87FFC0), 'pointer', ['pointer', 'pointer', 'pointer']);
    const getCookieVal = new NativeFunction(itunesBase.add(0xBDE500), 'pointer', ['pointer']);
    const getKbsync = new NativeFunction(itunesBase.add(0x74D210), 'pointer', ['uint32', 'uint32', 'pointer']);

    getHeader = (url) => {
        const globalContext = itunesBase.add(0x22A9B18).readPointer();
        const otpGlobalContext = globalContext.isNull() ? null : globalContext.add(62716).readPointer();

        const otpContext = Memory.alloc(128);
        otpContext.writePointer(otpGlobalContext);
        otpContext.add(27).writeU8(1);

        const urlBuffer = Memory.allocUtf8String(url);
        const urlData = CFURLCreateWithBytes(cfAllocator, urlBuffer, url.length, 0x8000100, 0);

        const hdrDict = prepareAppleHdrWrap(NULL, urlData, otpContext);
        const hdrOutput = readCFDict(hdrDict);

        const guid = hdrOutput['X-Guid'];
        delete hdrOutput['X-Guid'];

        const cookieCFStr = getCookieVal(urlData);
        const cookieStr = readCFStr(cookieCFStr);
        hdrOutput['Cookie'] = cookieStr;

        const kbsyncPtr = getKbsync(kbsyncContext, 1, otpGlobalContext);
        const kbSyncData = readCFData(kbsyncPtr);
        if (!kbSyncData) {
            send('请登录iTunes');
        }else {
            send('获取数据成功,服务器运行正常')
        }

        const kbsyncValues = [...new Uint8Array(kbSyncData)].map(x => x.toString(16).padStart(2, '0')).join('');

        return { headers: hdrOutput, kbsync: kbsyncValues, guid: guid };
    };
}

// 初始化并导出 getHeader 方法
rpc.exports = {
    getHeader: async (url) => {
        if (!getHeader) {
            await init();
        }
        return getHeader(url);
    },
};
