-- Render the report's Markdown tables with visible row and column rules.
local function cell_latex(cell)
  local result = pandoc.write(pandoc.Pandoc(cell.contents), 'latex')
  return result:gsub('^[ \t\r\n]+', ''):gsub('[ \t\r\n]+$', ''):gsub('\n+', ' ')
end

local function add_rows(lines, rows)
  for _, row in ipairs(rows) do
    local cells = {}
    for _, cell in ipairs(row.cells) do
      cells[#cells + 1] = cell_latex(cell)
    end
    lines[#lines + 1] = table.concat(cells, ' & ') .. ' \\\\'
    lines[#lines + 1] = '\\hline'
  end
end

function Table(tbl)
  local columns = #tbl.colspecs
  local lines = {
    '\\begin{tabularx}{\\linewidth}{|' .. string.rep('Y|', columns) .. '}',
    '\\hline'
  }
  add_rows(lines, tbl.head.rows)
  for _, body in ipairs(tbl.bodies) do
    add_rows(lines, body.head)
    add_rows(lines, body.body)
  end
  add_rows(lines, tbl.foot.rows)
  lines[#lines + 1] = '\\end{tabularx}'
  return pandoc.RawBlock('latex', table.concat(lines, '\n'))
end
