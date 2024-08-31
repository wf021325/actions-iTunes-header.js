const frida = require('frida');
const fs = require('fs');
const path = require('path');
const express = require('express');

// 附加到 iTunes 进程的函数
async function attachToProcess(procName) {
    try {
        const session = await frida.attach(procName);
        return session;
    } catch (error) {
        console.error(`错误: 附加到进程 ${procName} 时发生异常: ${error.message}`);
        console.log('请检查iTunes客户端是否运行')
        process.exit(1);
    }
}

async function main() {
    const session = await attachToProcess('iTunes.exe');
    const filePath = path.join(__dirname, 'get_header_rpc.js');
    const scriptContent = fs.readFileSync(filePath, 'utf8');
    const script = await session.createScript(scriptContent);

    script.message.connect(onMessage);
    await script.load();
    const rpc = script.exports;
    const app = express();

    app.get('/', async (req, res) => {
        const hdrUrl = req.query.url || "https://p46-buy.itunes.apple.com/WebObjects/MZBuy.woa/wa/buyProduct";
        const retHdrs = await rpc.getHeader(hdrUrl);
		//console.log(retHdrs)
        res.json(retHdrs);
    });

    app.listen(9000, () => {
        console.log('server run in  http://127.0.0.1:9000');
    });
}

function onMessage(message, data) {
    if (message.type === 'send') {
        console.error("Frida: %s", message.payload);
    } else if (message.type === 'error') {
        console.error("Frida error: %s", message.stack);
    }
}

main().catch(console.error);
