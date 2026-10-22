local M = {}

M.create_directory = function()
    local dir_name = vim.fn.input('Directory name: ')
    if dir_name == '' then
        vim.notify('Directory creation cancelled', vim.log.levels.WARN, {
            title = 'Directory Creation',
            timeout = 2000
        })
        return
    end
    
    local cwd = vim.fn.getcwd()
    local new_dir = cwd .. '/' .. dir_name
    
    local success = vim.fn.mkdir(new_dir, 'p')
    if success == 1 then
        vim.notify('Created directory: ' .. new_dir, vim.log.levels.INFO, {
            title = 'Directory Creation',
            timeout = 2000,
            icon = '📁'
        })
    else
        vim.notify('Failed to create directory: ' .. new_dir, vim.log.levels.ERROR, {
            title = 'Directory Creation',
            timeout = 3000
        })
    end
end

return M
