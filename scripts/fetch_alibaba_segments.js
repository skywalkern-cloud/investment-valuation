#!/usr/bin/env node
/**
 * 阿里巴巴分部数据自动抓取脚本
 * 使用 Playwright 从阿里巴巴投资者关系页面抓取各分部营收数据
 * 
 * 数据来源：
 * 1. 季报发布页面 (press release)
 * 2. 投资者关系网站的财务数据区块
 * 
 * 输出：更新 stocks/09988_alibaba/manual_data.yaml
 */

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');

const ALI_MANUAL_PATH = path.join(__dirname, '../stocks/09988_alibaba/manual_data.yaml');
const LOG_FILE = path.join(__dirname, '../logs/alibaba_segments.log');

function log(msg) {
    const ts = new Date().toISOString();
    const line = `[${ts}] ${msg}\n`;
    fs.appendFileSync(LOG_FILE, line);
    console.log(msg);
}

async function fetchAlibabaSegments() {
    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
        userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        viewport: { width: 1280, height: 800 },
    });
    const page = await context.newPage();
    
    // 记录所有请求，便于调试
    const errors = [];
    page.on('console', msg => {
        if (msg.type() === 'error') errors.push(msg.text());
    });
    
    const results = {};
    
    try {
        // 方式1: 直接访问季报页面（HTML格式，包含分部数据）
        log('=== 方式1: 尝试阿里巴巴季报发布页 ===');
        
        // 尝试访问阿里巴巴FY2025 Q4季报（2025年5月发布）
        const quarterEarningsUrls = [
            // 英文版季报
            'https://www.alibabagroup.com/en-US/ir/financial-news',
            // 中文版季报
            'https://www.alibabagroup.com.cn/zh-cn/ir/financial-news',
        ];
        
        for (const url of quarterEarningsUrls) {
            try {
                log(`访问: ${url}`);
                const response = await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
                log(`  状态: ${response.status()}`);
                
                if (response.status() === 200) {
                    // 等待页面内容加载
                    await page.waitForTimeout(3000);
                    
                    // 获取页面文本内容
                    const content = await page.content();
                    log(`  内容长度: ${content.length} bytes`);
                    
                    // 提取页面文本
                    const text = await page.evaluate(() => document.body.innerText);
                    
                    // 搜索分部相关关键词
                    const segmentKeywords = ['Cloud Intelligence', 'Cloud', 'Commerce', 'International', 'Cainiao', 'Lazada', 'Taobao', 'Tmall', 'Revenue', 'Revenue Breakdown'];
                    for (const kw of segmentKeywords) {
                        if (text.includes(kw)) {
                            log(`  ✅ 找到关键词: ${kw}`);
                        }
                    }
                    
                    // 尝试提取金额数据 - 搜索常见的金额模式 (e.g., "RMB 8.8 billion", "26,583", "¥93.6")
                    const amountPatterns = [
                        /Cloud[^$]*?(?:RMB|USD|¥|\$)\s*([\d,]+)\s*(?:billion|million|B|M)?/gi,
                        /¥\s*([\d,]+)\s*(?:billion|million|B|M)?/gi,
                        /RMB\s*([\d,]+)\s*(?:billion|million|B|M)?/gi,
                    ];
                    
                    for (const pattern of amountPatterns) {
                        const matches = text.match(pattern);
                        if (matches) {
                            log(`  金额匹配: ${matches.slice(0, 5).join(' | ')}`);
                        }
                    }
                    
                    // 如果找到关键数据，尝试解析
                    if (text.includes('Cloud') && text.includes('Revenue')) {
                        log('  🔍 检测到 Cloud 相关内容，提取分部数据...');
                        results.content = text.substring(0, 5000);
                    }
                }
            } catch (e) {
                log(`  ❌ 加载失败: ${e.message}`);
            }
        }
        
        // 方式2: 直接访问可解析的财务数据页面
        log('\n=== 方式2: 尝试 East Money 港股财务 ===');
        try {
            const emResponse = await page.goto(
                'https://datacenter.eastmoney.com/api/data/v1/get?reportName=RPT_LICO_FN_CPD&columns=SECURITY_CODE,REPORTDATE,TOTAL_OPERATE_INCOME,PARENT_NETPROFIT&filter=(SECUCODE=%2209988.SZ%22)&pageSize=4',
                { timeout: 15000 }
            );
            log(`  East Money状态: ${emResponse.status()}`);
            const emText = await page.evaluate(() => document.body.innerText);
            log(`  内容: ${emText.substring(0, 500)}`);
        } catch (e) {
            log(`  ❌: ${e.message}`);
        }
        
        // 方式3: 尝试访问阿里巴巴股价详情页（含财务摘要）
        log('\n=== 方式3: 尝试同花顺港股 ===');
        try {
            await page.goto('https://stockpage.10jqka.com.cn/09988/', { timeout: 20000 });
            await page.waitForTimeout(3000);
            const thsText = await page.evaluate(() => document.body.innerText);
            log(`  同花顺内容长度: ${thsText.length}`);
            
            // 搜索分部关键词
            const cloudMatch = thsText.match(/云.{0,20}(?:收入|营收|RMB|¥)[\s:：]*([\d,]+)/i);
            const commMatch = thsText.match(/(?:电商|商业|Commerce).{0,20}(?:收入|营收|RMB|¥)[\s:：]*([\d,]+)/i);
            if (cloudMatch) log(`  找到云业务: ${cloudMatch[0]}`);
            if (commMatch) log(`  找到商业: ${commMatch[0]}`);
        } catch (e) {
            log(`  ❌: ${e.message}`);
        }
        
    } finally {
        await browser.close();
    }
    
    return results;
}

// 主流程
async function main() {
    log('='.repeat(60));
    log('阿里巴巴分部数据抓取开始');
    
    try {
        const data = await fetchAlibabaSegments();
        
        if (data && data.content) {
            log('\n=== 获取到的内容片段 ===');
            log(data.content.substring(0, 2000));
            
            // TODO: 解析分部数据并更新 manual_data.yaml
            // 这里需要根据实际页面结构调整解析逻辑
            log('\n⚠️  需要人工检查内容并手动更新分部数据');
            log('   建议访问: https://www.alibabagroup.com/en-US/ir/financial-news');
        } else {
            log('\n❌ 未能获取到有效数据');
            log('   建议方案:');
            log('   1. 使用 Selenium/Playwright 完整渲染页面');
            log('   2. 接入 Wind/Tonghuashun 等专业数据API');
            log('   3. 定期手动更新 manual_data.yaml');
        }
        
    } catch (err) {
        log(`❌ 脚本异常: ${err.message}`);
        log(err.stack);
    }
    
    log('\n完成');
}

main();
