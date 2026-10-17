import React from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './app/App'
import { DataProvider, PulseData, createWasmEngine } from './data'
import './theme/base.css'

const data = new PulseData({ engine: createWasmEngine })

createRoot(document.getElementById('root')!).render(<React.StrictMode><DataProvider data={data}><App /></DataProvider></React.StrictMode>)
