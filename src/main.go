package main

import (
	"os"

	"hiku/config"
	"hiku/l4"
	"hiku/server"

	"github.com/urfave/cli"
)

func createCliApp() *cli.App {
	app := cli.NewApp()
	app.Usage = "Hiku Scheduler"
	app.UsageText = "hiku COMMAND [ARG...]"
	app.ArgsUsage = "ArgsUsage"
	app.EnableBashCompletion = true
	app.HideVersion = true

	configFlag := cli.StringFlag{
		Name:  "config, c",
		Usage: "Config json file",
		Value: "hiku.json",
	}
	l4ConfigFlag := cli.StringFlag{
		Name:  "config, c",
		Usage: "Config json file",
		Value: "l4.json",
	}
	app.Commands = []cli.Command{
		cli.Command{Name: "start", Usage: "Start Hiku",
			UsageText:   "hiku start [-c|--config=FILEPATH]",
			Description: "The scheduler starts with settings from config json file.",
			Flags:       []cli.Flag{configFlag},
			Action: func(c *cli.Context) error {
				cfgFilePath := c.String("config")
				cfg := config.LoadConfigFromFile(cfgFilePath)
				return server.Start(cfg.ToConfig())
			},
		},
		cli.Command{Name: "l4", Usage: "Start Hiku in L4 mode",
			UsageText:   "hiku l4 [-c|--config=FILEPATH]",
			Description: "The scheduler attaches the eBPF steering programs and populates the maps from config json file.",
			Flags:       []cli.Flag{l4ConfigFlag},
			Action: func(c *cli.Context) error {
				cfgFilePath := c.String("config")
				cfg := l4.LoadConfigFromFile(cfgFilePath)
				return l4.Start(cfg.ToConfig())
			},
		},
	}
	return app
}

func main() {
	app := createCliApp()
	app.Run(os.Args)
}
